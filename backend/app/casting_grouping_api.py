"""HTTP adapter for the pure Casting grouping preview."""
from __future__ import annotations

from typing import Any
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .importers.casting_grouping import build_casting_grouping_preview
from .importers.casting_grouping_catalog import build_casting_grouping_catalog_records
from sqlalchemy.orm import Session
from .db import get_db


router = APIRouter(tags=["castings"])


class CastingGroupingPreviewRequest(BaseModel):
    """Caller-supplied record snapshots; no database lookup is performed."""

    records: list[dict[str, Any]] = Field(min_length=1, max_length=10_000)


@router.post("/castings/grouping-preview")
def preview_casting_grouping(request: CastingGroupingPreviewRequest) -> dict:
    """Return proposed groups only; this endpoint never changes catalog data."""
    try:
        return build_casting_grouping_preview(request.records)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc



class CastingGroupingCatalogPreviewRequest(BaseModel):
    """Explicit product-line scope for a read-only catalog snapshot."""
    product_line: str = Field(min_length=1, max_length=120)
    catalog_year: int | None = Field(default=None, ge=1968, le=2100)


@router.post("/castings/grouping-preview/from-catalog")
def preview_casting_grouping_from_catalog(
    request: CastingGroupingCatalogPreviewRequest,
    session: Session = Depends(get_db),
) -> dict:
    """Build provisional grouping proposals from catalog rows using SELECT only."""
    try:
        records = build_casting_grouping_catalog_records(
            session, product_line=request.product_line, catalog_year=request.catalog_year
        )
        preview = build_casting_grouping_preview(records) if records else {
            "contract": "hw_catalog.casting_grouping_preview",
            "contract_version": 1,
            "mode": "preview_only",
            "writes_to_catalog": False,
            "grouping_key": ["product_line", "catalog_year", "collector_number"],
            "groups": [],
            "manual_review": [],
            "conflicts": [],
            "summary": {
                "records_received": 0, "proposed_groups": 0,
                "records_requiring_manual_review": 0,
                "groups_requiring_manual_review": 0, "conflicts": 0,
            },
        }
        evidence_by_record = {
            record["record_id"]: record.get("evidence_review_status_counts", {})
            for record in records
        }
        existing_to_proposals: dict[str, set[str]] = defaultdict(set)
        for group in preview["groups"]:
            for member in group["records"]:
                member["evidence_review_status_counts"] = evidence_by_record.get(member["record_id"], {})
                casting_id = member.get("existing_casting_id")
                if casting_id:
                    existing_to_proposals[casting_id].add(group["proposal_id"])

        plan_items = []
        evidence_totals: dict[str, int] = {}
        for group in preview["groups"]:
            members = group["records"]
            casting_ids = sorted({m["existing_casting_id"] for m in members if m.get("existing_casting_id")})
            split_ids = [cid for cid in casting_ids if len(existing_to_proposals[cid]) > 1]
            if group["requires_manual_review"]:
                action = "manual_review"
            elif len(casting_ids) > 1:
                action = "merge_candidate_manual_review"
            elif split_ids:
                action = "split_candidate_manual_review"
            elif len(casting_ids) == 1:
                action = "keep_existing_link_candidate"
            else:
                action = "new_casting_candidate"
            status_counts: dict[str, int] = {}
            for member in members:
                for status, count in member.get("evidence_review_status_counts", {}).items():
                    status_counts[status] = status_counts.get(status, 0) + count
                    evidence_totals[status] = evidence_totals.get(status, 0) + count
            plan_items.append({
                "proposal_id": group["proposal_id"],
                "group_key": group["group_key"],
                "action": action,
                "existing_casting_ids": casting_ids,
                "affected_release_ids": [m["release_id"] for m in members],
                "evidence_review_status_counts": status_counts,
                "requires_manual_review": action == "manual_review" or action.endswith("_manual_review"),
            })

        approved_evidence = evidence_totals.get("approved", 0)
        remediation_plan = {
            "mode": "report_only",
            "writes_to_catalog": False,
            "items": plan_items,
            "summary": {
                "keep_existing_link_candidates": sum(x["action"] == "keep_existing_link_candidate" for x in plan_items),
                "split_candidates_requiring_review": sum(x["action"] == "split_candidate_manual_review" for x in plan_items),
                "merge_candidates_requiring_review": sum(x["action"] == "merge_candidate_manual_review" for x in plan_items),
                "new_casting_candidates": sum(x["action"] == "new_casting_candidate" for x in plan_items),
                "manual_review_items": sum(x["action"] == "manual_review" for x in plan_items),
                "evidence_review_status_counts": evidence_totals,
                "approved_evidence": approved_evidence,
                "non_approved_evidence": sum(v for k, v in evidence_totals.items() if k != "approved"),
                "safe_to_apply_automatically": False,
            },
        }
        return {
            **preview,
            "remediation_plan": remediation_plan,
            "catalog_snapshot": {
                "product_line": " ".join(request.product_line.split()),
                "catalog_year": request.catalog_year,
                "records_loaded": len(records),
                "source": "catalog_database",
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

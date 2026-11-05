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
            if split_ids:
                action = "split_candidate_manual_review"
            elif len(casting_ids) > 1:
                action = "merge_candidate_manual_review"
            elif group["requires_manual_review"]:
                action = "manual_review"
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
                "manual_review_items": sum(x["requires_manual_review"] for x in plan_items),
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


# Persistent review workflow. These endpoints write only to dedicated review tables.
import hashlib as _hashlib
import json as _json
from datetime import timezone as _timezone
from typing import Literal as _Literal

from sqlalchemy import select as _select
from .models import (
    CastingGroupingReviewDecision,
    CastingGroupingReviewSession,
)


def _canonical_sha256(value: object) -> str:
    encoded = _json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return _hashlib.sha256(encoded).hexdigest()


def _current_catalog_input_fingerprint(session: Session, product_line: str, catalog_year: int | None) -> str:
    records = build_casting_grouping_catalog_records(
        session, product_line=product_line, catalog_year=catalog_year
    )
    return _canonical_sha256(records)


def _current_review_fingerprints(
    session: Session, product_line: str, catalog_year: int | None
) -> tuple[str, str]:
    input_fingerprint = _current_catalog_input_fingerprint(
        session, product_line, catalog_year
    )
    report = preview_casting_grouping_from_catalog(
        CastingGroupingCatalogPreviewRequest(
            product_line=product_line, catalog_year=catalog_year
        ),
        session,
    )
    return input_fingerprint, _canonical_sha256(report)


def _review_decision_payload(decision: CastingGroupingReviewDecision) -> dict:
    created_at = decision.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=_timezone.utc)
    return {
        "id": decision.id,
        "session_id": decision.session_id,
        "proposal_id": decision.proposal_id,
        "disposition": decision.disposition,
        "reviewer_label": decision.reviewer_label,
        "reason": decision.reason,
        "previous_decision_id": decision.previous_decision_id,
        "created_at": created_at.isoformat(),
    }


class CastingGroupingReviewSessionRequest(BaseModel):
    product_line: str = Field(min_length=1, max_length=120)
    catalog_year: int | None = Field(default=None, ge=1968, le=2100)


class CastingGroupingReviewDecisionRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=160)
    disposition: _Literal["accepted", "rejected", "needs_more_evidence"]
    reviewer_label: str = Field(min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=4000)


@router.post("/castings/grouping-review-sessions/from-catalog")
def create_casting_grouping_review_session(
    request: CastingGroupingReviewSessionRequest,
    session: Session = Depends(get_db),
) -> dict:
    """Persist a fresh immutable preview snapshot; catalog rows remain read-only."""
    product_line = " ".join(request.product_line.split())
    if not product_line:
        raise HTTPException(status_code=422, detail="product_line must not be blank.")
    try:
        report = preview_casting_grouping_from_catalog(
            CastingGroupingCatalogPreviewRequest(
                product_line=product_line, catalog_year=request.catalog_year
            ),
            session,
        )
        input_fingerprint = _current_catalog_input_fingerprint(
            session, product_line, request.catalog_year
        )
        snapshot_fingerprint = _canonical_sha256(report)
        review_session = CastingGroupingReviewSession(
            product_line=product_line,
            catalog_year=request.catalog_year,
            contract=report.get("contract", "hw_catalog.casting_grouping_preview"),
            contract_version=report.get("contract_version", 1),
            grouping_key=report.get("grouping_key", []),
            snapshot=report,
            snapshot_sha256=snapshot_fingerprint,
            catalog_input_fingerprint=input_fingerprint,
        )
        session.add(review_session)
        session.commit()
        session.refresh(review_session)
    except HTTPException:
        session.rollback()
        raise
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise

    return {
        "mode": "review_session_created",
        "writes_to_catalog": False,
        "session_id": review_session.id,
        "created_at": review_session.created_at.isoformat(),
        "product_line": review_session.product_line,
        "catalog_year": review_session.catalog_year,
        "snapshot_sha256": review_session.snapshot_sha256,
        "catalog_input_fingerprint": review_session.catalog_input_fingerprint,
        "snapshot": review_session.snapshot,
        "decisions": [],
        "stale": False,
    }


@router.get("/castings/grouping-review-sessions/{session_id}")
def get_casting_grouping_review_session(
    session_id: str,
    session: Session = Depends(get_db),
) -> dict:
    review_session = session.get(CastingGroupingReviewSession, session_id)
    if review_session is None:
        raise HTTPException(status_code=404, detail="Review session not found.")
    current_fingerprint, current_snapshot_fingerprint = _current_review_fingerprints(
        session, review_session.product_line, review_session.catalog_year
    )
    stale = (
        current_fingerprint != review_session.catalog_input_fingerprint
        or current_snapshot_fingerprint != review_session.snapshot_sha256
    )
    decisions = session.scalars(
        _select(CastingGroupingReviewDecision)
        .where(CastingGroupingReviewDecision.session_id == session_id)
        .order_by(CastingGroupingReviewDecision.created_at, CastingGroupingReviewDecision.id)
    ).all()
    latest_by_proposal = {}
    for decision in decisions:
        latest_by_proposal[decision.proposal_id] = _review_decision_payload(decision)
    return {
        "mode": "review_session_read",
        "writes_to_catalog": False,
        "session_id": review_session.id,
        "created_at": review_session.created_at.isoformat(),
        "product_line": review_session.product_line,
        "catalog_year": review_session.catalog_year,
        "contract": review_session.contract,
        "contract_version": review_session.contract_version,
        "grouping_key": review_session.grouping_key,
        "snapshot_sha256": review_session.snapshot_sha256,
        "catalog_input_fingerprint": review_session.catalog_input_fingerprint,
        "snapshot": review_session.snapshot,
        "decisions": list(latest_by_proposal.values()),
        "stale": stale,
    }


@router.get("/castings/grouping-review-sessions/{session_id}/decisions")
def list_casting_grouping_review_decisions(
    session_id: str,
    session: Session = Depends(get_db),
) -> dict:
    review_session = session.get(CastingGroupingReviewSession, session_id)
    if review_session is None:
        raise HTTPException(status_code=404, detail="Review session not found.")
    current_fingerprint, current_snapshot_fingerprint = _current_review_fingerprints(
        session, review_session.product_line, review_session.catalog_year
    )
    stale = (
        current_fingerprint != review_session.catalog_input_fingerprint
        or current_snapshot_fingerprint != review_session.snapshot_sha256
    )
    decisions = session.scalars(
        _select(CastingGroupingReviewDecision)
        .where(CastingGroupingReviewDecision.session_id == session_id)
        .order_by(CastingGroupingReviewDecision.created_at, CastingGroupingReviewDecision.id)
    ).all()
    return {
        "mode": "review_decision_history",
        "writes_to_catalog": False,
        "session_id": session_id,
        "stale": stale,
        "total": len(decisions),
        "items": [_review_decision_payload(item) for item in decisions],
    }


@router.post("/castings/grouping-review-sessions/{session_id}/decisions")
def append_casting_grouping_review_decision(
    session_id: str,
    request: CastingGroupingReviewDecisionRequest,
    session: Session = Depends(get_db),
) -> dict:
    """Append one reviewer decision. This never authorizes or performs catalog apply."""
    review_session = session.get(CastingGroupingReviewSession, session_id)
    if review_session is None:
        raise HTTPException(status_code=404, detail="Review session not found.")

    current_fingerprint, current_snapshot_fingerprint = _current_review_fingerprints(
        session, review_session.product_line, review_session.catalog_year
    )
    if (
        current_fingerprint != review_session.catalog_input_fingerprint
        or current_snapshot_fingerprint != review_session.snapshot_sha256
    ):
        raise HTTPException(
            status_code=409,
            detail="Review session is stale; create a fresh session before recording decisions.",
        )

    proposal_ids = {
        item.get("proposal_id")
        for item in review_session.snapshot.get("remediation_plan", {}).get("items", [])
    }
    if request.proposal_id not in proposal_ids:
        raise HTTPException(status_code=404, detail="Proposal does not belong to this session.")

    previous = session.scalar(
        _select(CastingGroupingReviewDecision)
        .where(
            CastingGroupingReviewDecision.session_id == session_id,
            CastingGroupingReviewDecision.proposal_id == request.proposal_id,
        )
        .order_by(
            CastingGroupingReviewDecision.created_at.desc(),
            CastingGroupingReviewDecision.id.desc(),
        )
        .limit(1)
    )
    reviewer_label = request.reviewer_label.strip()
    if not reviewer_label:
        raise HTTPException(status_code=422, detail="reviewer_label must not be blank.")
    decision = CastingGroupingReviewDecision(
        session_id=session_id,
        proposal_id=request.proposal_id,
        disposition=request.disposition,
        reviewer_label=reviewer_label,
        reason=request.reason,
        previous_decision_id=previous.id if previous else None,
    )
    try:
        session.add(decision)
        session.commit()
        session.refresh(decision)
    except Exception:
        session.rollback()
        raise
    return {
        "mode": "review_decision_recorded",
        "writes_to_catalog": False,
        "decision": _review_decision_payload(decision),
    }

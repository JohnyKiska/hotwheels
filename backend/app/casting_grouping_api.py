"""HTTP adapters for read-only Casting grouping previews."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .db import get_db
from .importers.casting_grouping import build_casting_grouping_preview
from .importers.casting_grouping_catalog import build_casting_grouping_catalog_records


router = APIRouter(tags=["castings"])


class CastingGroupingPreviewRequest(BaseModel):
    """Caller-supplied record snapshots; no database lookup is performed."""

    records: list[dict[str, Any]] = Field(min_length=1, max_length=10_000)


class CastingGroupingCatalogPreviewRequest(BaseModel):
    """Explicit product-line scope for a read-only catalog snapshot."""

    product_line: str = Field(min_length=1, max_length=120)
    catalog_year: int | None = Field(default=None, ge=1968, le=2100)


@router.post("/castings/grouping-preview")
def preview_casting_grouping(request: CastingGroupingPreviewRequest) -> dict:
    """Return proposals from caller snapshots; never changes catalog data."""
    try:
        return build_casting_grouping_preview(request.records)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/castings/grouping-preview/from-catalog")
def preview_casting_grouping_from_catalog(
    request: CastingGroupingCatalogPreviewRequest,
    session: Session = Depends(get_db),
) -> dict:
    """Build proposals from existing catalog rows using SELECT-only snapshots."""
    try:
        records = build_casting_grouping_catalog_records(
            session,
            product_line=request.product_line,
            catalog_year=request.catalog_year,
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
                "records_received": 0,
                "proposed_groups": 0,
                "records_requiring_manual_review": 0,
                "groups_requiring_manual_review": 0,
                "conflicts": 0,
            },
        }
        return {
            **preview,
            "catalog_snapshot": {
                "product_line": " ".join(request.product_line.split()),
                "catalog_year": request.catalog_year,
                "records_loaded": len(records),
                "source": "catalog_database",
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

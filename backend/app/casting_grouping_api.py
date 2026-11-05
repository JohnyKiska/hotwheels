"""HTTP adapter for the pure Casting grouping preview."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .importers.casting_grouping import build_casting_grouping_preview


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

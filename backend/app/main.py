from typing import Literal

from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .casting_grouping_api import router as casting_grouping_router
from .importers.all_hot_wheels import preview_all_hot_wheels_html
from .importers.mainline import preview_mainline_fandom_html, preview_mainline_tsv
from .importers.observations import preview_to_observations
from .importers.matcher import match_import_observation
from .importers.preview_diff import build_release_claim_diff
from .models import Casting, Release, ReleaseSeries, Series
from .conflict_queue import get_conflict_detail, list_conflicts
from .conflict_resolution import (
    InvalidConflictResolution,
    UnknownConflict,
    resolve_conflict,
    revise_conflict_resolution,
)

app = FastAPI(
    title="Hot Wheels Catalog API",
    version="0.1.0",
    description="Backend foundation for the test Hot Wheels catalog.",
)
app.include_router(casting_grouping_router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a basic health status without accessing catalog data."""
    return {"status": "ok"}


class MainlinePreviewRequest(BaseModel):
    """Clipboard content and catalog year for a read-only preview."""

    text: str = Field(min_length=1, max_length=500_000)
    catalog_year: int = Field(ge=1968, le=2100)


@app.post("/imports/mainline/preview", tags=["imports"])
def preview_mainline_import(request: MainlinePreviewRequest) -> dict:
    """Parse Mainline TSV for review only; never writes to the catalog."""
    try:
        return preview_mainline_tsv(request.text, request.catalog_year)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class MainlineHtmlPreviewRequest(BaseModel):
    """A saved Fandom yearly HTML page for a read-only preview."""

    text: str = Field(min_length=1, max_length=2_000_000)
    catalog_year: int = Field(ge=1968, le=2100)


@app.post("/imports/mainline/fandom-html-preview", tags=["imports"])
def preview_mainline_fandom_html_import(request: MainlineHtmlPreviewRequest) -> dict:
    """Parse the primary Fandom yearly list table; never writes to the catalog."""
    try:
        return preview_mainline_fandom_html(request.text, request.catalog_year)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AllHotWheelsHtmlPreviewRequest(BaseModel):
    """A saved individual All Hot Wheels page for a read-only preview."""

    text: str = Field(min_length=1, max_length=2_000_000)
    expected_year: int | None = Field(default=None, ge=1968, le=2100)


@app.post("/imports/all-hot-wheels/html-preview", tags=["imports"])
def preview_all_hot_wheels_html_import(request: AllHotWheelsHtmlPreviewRequest) -> dict:
    """Parse one saved All Hot Wheels page; never writes to the catalog."""
    try:
        return preview_all_hot_wheels_html(request.text, request.expected_year)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc




class ImportPipelinePreviewRequest(BaseModel):
    """One source payload and optional explicit catalog Release selection."""

    source: Literal["mainline_tsv", "fandom_html", "all_hot_wheels_html"]
    text: str = Field(min_length=1, max_length=2_000_000)
    catalog_year: int | None = Field(default=None, ge=1968, le=2100)
    expected_year: int | None = Field(default=None, ge=1968, le=2100)
    record_index: int = Field(default=0, ge=0)
    selected_release_id: str | None = None

    @model_validator(mode="after")
    def validate_source_year(self):
        if self.source in ("mainline_tsv", "fandom_html") and self.catalog_year is None:
            raise ValueError("catalog_year is required for Mainline sources.")
        if self.source == "all_hot_wheels_html" and self.catalog_year is not None:
            raise ValueError("catalog_year is not accepted for All Hot Wheels pages.")
        return self


def _release_preview_snapshot(session: Session, release: Release) -> dict:
    casting = session.get(Casting, release.casting_id)
    series_names = session.scalars(
        select(Series.name)
        .join(ReleaseSeries, ReleaseSeries.series_id == Series.id)
        .where(ReleaseSeries.release_id == release.id)
    ).all()
    return {
        "id": release.id,
        "name": release.name,
        "casting_name": casting.name if casting else None,
        "catalog_year": release.catalog_year,
        "assortment_number": release.assortment_number,
        "series_names": list(series_names),
    }


@app.post("/imports/preview", tags=["imports"])
def preview_import_pipeline(
    request: ImportPipelinePreviewRequest,
    session: Session = Depends(get_db),
) -> dict:
    """Run parser → observation → matcher → optional claim diff, without writes."""
    try:
        if request.source == "mainline_tsv":
            parsed = preview_mainline_tsv(request.text, request.catalog_year)
        elif request.source == "fandom_html":
            parsed = preview_mainline_fandom_html(request.text, request.catalog_year)
        else:
            parsed = preview_all_hot_wheels_html(request.text, request.expected_year)

        adapted = preview_to_observations(parsed)
        observations = adapted["observations"]
        if request.record_index >= len(observations):
            raise HTTPException(
                status_code=422,
                detail=f"record_index {request.record_index} is out of range; "
                       f"{len(observations)} observations are available.",
            )

        observation = observations[request.record_index]
        matcher_input = {
            **observation,
            "mode": "preview_only",
            "writes_to_catalog": False,
        }
        matching = match_import_observation(session, matcher_input)

        selected_release = None
        claim_diff = None
        if request.selected_release_id:
            release = session.get(Release, request.selected_release_id)
            if release is None:
                raise HTTPException(status_code=404, detail="Selected Release not found.")
            selected_release = _release_preview_snapshot(session, release)
            claim_diff = build_release_claim_diff(matcher_input, selected_release)

        return {
            "contract": "hw_catalog.import_pipeline_preview",
            "contract_version": 1,
            "mode": "preview_only",
            "writes_to_catalog": False,
            "source": adapted["source"],
            "parser_summary": adapted["summary"],
            "parser_issues": adapted["issues"],
            "record_index": request.record_index,
            "records_available": len(observations),
            "observation": observation,
            "matching": matching,
            "selected_release": selected_release,
            "claim_diff": claim_diff,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/conflicts", tags=["review"])
def get_conflicts(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    conflict_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> dict:
    """List conflicts for review; defaults to unresolved conflicts."""
    try:
        return list_conflicts(
            session,
            status=status,
            severity=severity,
            conflict_type=conflict_type,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc



@app.get("/conflicts/{conflict_id}", tags=["review"])
def get_conflict(
    conflict_id: str,
    session: Session = Depends(get_db),
) -> dict:
    """Return one conflict with its evidence and source metadata."""
    conflict = get_conflict_detail(session, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    return conflict


class ConflictResolutionRequest(BaseModel):
    status: str
    resolution: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    actor_type: str = "human"
    actor_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


@app.post("/conflicts/{conflict_id}/resolve", tags=["review"])
def post_conflict_resolution(
    conflict_id: str,
    request: ConflictResolutionRequest,
    session: Session = Depends(get_db),
) -> dict:
    """Record an explicit, auditable manual conflict decision."""
    try:
        conflict = resolve_conflict(
            session,
            conflict_id=conflict_id,
            status=request.status,
            resolution=request.resolution,
            reason=request.reason,
            actor_type=request.actor_type,
            actor_id=request.actor_id,
            evidence_ids=request.evidence_ids,
        )
        session.commit()
    except UnknownConflict as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail="Conflict not found") from exc
    except InvalidConflictResolution as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise

    return {
        "id": conflict.id,
        "status": conflict.status,
        "resolution": conflict.resolution,
        "resolution_reason": conflict.resolution_reason,
        "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
    }


class ConflictResolutionRevisionRequest(BaseModel):
    status: str
    resolution: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    actor_type: str = "human"
    actor_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


@app.post("/conflicts/{conflict_id}/revise-resolution", tags=["review"])
def post_conflict_resolution_revision(
    conflict_id: str,
    request: ConflictResolutionRevisionRequest,
    session: Session = Depends(get_db),
) -> dict:
    """Revise a final decision by appending a new audit event."""
    try:
        conflict = revise_conflict_resolution(
            session,
            conflict_id=conflict_id,
            status=request.status,
            resolution=request.resolution,
            reason=request.reason,
            actor_type=request.actor_type,
            actor_id=request.actor_id,
            evidence_ids=request.evidence_ids,
        )
        session.commit()
    except UnknownConflict as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail="Conflict not found") from exc
    except InvalidConflictResolution as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise

    return {
        "id": conflict.id,
        "status": conflict.status,
        "resolution": conflict.resolution,
        "resolution_reason": conflict.resolution_reason,
        "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
    }

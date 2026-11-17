"""Permission-protected API for human review of catalog conflicts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .account_api import _require_csrf, _require_permission
from .conflict_queue import get_conflict_detail, list_conflicts
from .conflict_resolution import (
    InvalidConflictResolution,
    UnknownConflict,
    resolve_conflict,
    revise_conflict_resolution,
)
from .db import get_db
from .models import User

router = APIRouter(prefix="/api/v1/admin/moderation", tags=["admin-moderation"])


class ConflictResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    resolution: str = Field(min_length=1, max_length=10000)
    reason: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=500)


class ConflictResolutionRevisionRequest(ConflictResolutionRequest):
    pass


@router.get("/conflicts")
def get_conflicts(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    conflict_type: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _actor: User = Depends(_require_permission("catalog.read")),
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


@router.get("/conflicts/{conflict_id}")
def get_conflict(
    conflict_id: str,
    _actor: User = Depends(_require_permission("catalog.read")),
    session: Session = Depends(get_db),
) -> dict:
    """Return one conflict with evidence and source metadata."""
    conflict = get_conflict_detail(session, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    return conflict


@router.post("/conflicts/{conflict_id}/resolve")
def post_conflict_resolution(
    conflict_id: str,
    body: ConflictResolutionRequest,
    request: Request,
    actor: User = Depends(_require_permission("catalog.update")),
    session: Session = Depends(get_db),
) -> dict:
    """Record an explicit, auditable human decision."""
    _require_csrf(request)
    try:
        conflict = resolve_conflict(
            session,
            conflict_id=conflict_id,
            status=body.status,
            resolution=body.resolution,
            reason=body.reason,
            actor_type="human",
            actor_id=actor.id,
            evidence_ids=body.evidence_ids,
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


@router.post("/conflicts/{conflict_id}/revise-resolution")
def post_conflict_resolution_revision(
    conflict_id: str,
    body: ConflictResolutionRevisionRequest,
    request: Request,
    actor: User = Depends(_require_permission("catalog.update")),
    session: Session = Depends(get_db),
) -> dict:
    """Revise a final decision while retaining the previous audit event."""
    _require_csrf(request)
    try:
        conflict = revise_conflict_resolution(
            session,
            conflict_id=conflict_id,
            status=body.status,
            resolution=body.resolution,
            reason=body.reason,
            actor_type="human",
            actor_id=actor.id,
            evidence_ids=body.evidence_ids,
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

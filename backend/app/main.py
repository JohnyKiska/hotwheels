from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .db import get_db
from .catalog_tree_api import router as catalog_tree_router
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


app.include_router(catalog_tree_router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a basic health status without accessing catalog data."""
    return {"status": "ok"}


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

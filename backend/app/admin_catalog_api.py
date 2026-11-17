"""Permission-protected catalog administration endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .account_api import _require_csrf, _require_permission
from .db import get_db
from .models import Casting, ChangeLog, User

router = APIRouter(prefix="/api/v1/admin/catalog", tags=["admin-catalog"])

CastingStatus = Literal["candidate", "under_review", "confirmed", "rejected"]


class CastingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    first_known_year: int | None = Field(default=None, ge=1968, le=2100)
    status: CastingStatus | None = None
    reason: str = Field(min_length=1, max_length=4000)


def _casting_payload(casting: Casting) -> dict:
    return {
        "id": casting.id,
        "name": casting.name,
        "description": casting.description,
        "first_known_year": casting.first_known_year,
        "status": casting.status,
        "created_at": casting.created_at.isoformat(),
        "updated_at": casting.updated_at.isoformat(),
    }


@router.get("/castings")
def list_castings(
    q: str | None = Query(default=None, max_length=240),
    status: CastingStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    """Search and paginate casting identities."""
    filters = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters.append(or_(Casting.name.ilike(term), Casting.description.ilike(term)))
    if status:
        filters.append(Casting.status == status)

    total = db.scalar(select(func.count(Casting.id)).where(*filters)) or 0
    rows = db.scalars(
        select(Casting)
        .where(*filters)
        .order_by(func.lower(Casting.name), Casting.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [_casting_payload(item) for item in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/castings/{casting_id}")
def get_casting(
    casting_id: str,
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    casting = db.get(Casting, casting_id)
    if casting is None:
        raise HTTPException(status_code=404, detail="Casting not found.")
    payload = _casting_payload(casting)
    payload["variants"] = [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "status": item.status,
        }
        for item in sorted(casting.variants, key=lambda item: (item.name or "", item.id))
    ]
    payload["releases_count"] = len(casting.releases)
    return payload


@router.patch("/castings/{casting_id}")
def patch_casting(
    casting_id: str,
    body: CastingPatch,
    request: Request,
    user: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    """Update editable casting fields and append a ChangeLog entry atomically."""
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty change reason is required.")

    changes = body.model_dump(exclude_unset=True)
    changes.pop("reason", None)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one casting field must be supplied.")
    if "name" in changes and (changes["name"] is None or not changes["name"].strip()):
        raise HTTPException(status_code=422, detail="Casting name cannot be empty.")
    if "name" in changes:
        changes["name"] = changes["name"].strip()

    casting = db.get(Casting, casting_id)
    if casting is None:
        raise HTTPException(status_code=404, detail="Casting not found.")

    old_values = {}
    new_values = {}
    for field, value in changes.items():
        current = getattr(casting, field)
        if current != value:
            old_values[field] = current
            new_values[field] = value
    if not new_values:
        return _casting_payload(casting)

    try:
        for field, value in new_values.items():
            setattr(casting, field, value)
        db.add(ChangeLog(
            entity_type="casting",
            entity_id=casting.id,
            action="update",
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_type="user",
            actor_id=user.id,
        ))
        db.commit()
        db.refresh(casting)
    except Exception:
        db.rollback()
        raise
    return _casting_payload(casting)

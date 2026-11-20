"""Authenticated endpoint for applying one reviewed import observation."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .account_api import _require_csrf, _require_permission
from .db import get_db
from .importers.apply import apply_import_observation
from .models import User

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


class ApplyObservationRequest(BaseModel):
    observation: dict[str, Any]
    reason: str | None = Field(default=None, max_length=500)


@router.post("/apply", status_code=201)
def apply_observation(
    body: ApplyObservationRequest,
    request: Request,
    user: User = Depends(_require_permission("catalog.create")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    try:
        result = apply_import_observation(db, body.observation, actor_id=user.id, reason=body.reason)
        db.commit()
        return {"status": "applied", "mode": "evidence_only", **result}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Concurrent import apply conflict; retry the operation.") from exc
    except Exception:
        db.rollback()
        raise

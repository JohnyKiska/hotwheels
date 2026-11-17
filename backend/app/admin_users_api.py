"""Administrative user and role management endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .account_api import _has_permission, _require_csrf, _require_permission
from .account_services import AccountServiceError, assign_role, revoke_role
from .db import get_db
from .models import (
    AuditEvent, EmailAddress, Permission, Role, RolePermission, User,
    UserRole, UserSession, utc_now,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-users"])


class RoleAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=1, max_length=4000)


class UserStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "suspended"]
    reason: str = Field(min_length=1, max_length=4000)


class RoleRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=4000)


def _is_super_admin(db: Session, user_id: str) -> bool:
    return db.scalar(
        select(UserRole.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            UserRole.user_id == user_id,
            Role.code == "super_admin",
            UserRole.revoked_at.is_(None),
            or_(UserRole.expires_at.is_(None), UserRole.expires_at > utc_now()),
        )
        .limit(1)
    ) is not None


def _active_roles(db: Session, user_id: str) -> list[dict]:
    rows = db.execute(
        select(Role, UserRole)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
            or_(UserRole.expires_at.is_(None), UserRole.expires_at > utc_now()),
        )
        .order_by(Role.name, Role.code)
    ).all()
    return [{
        "id": role.id, "code": role.code, "name": role.name,
        "assigned_at": assignment.assigned_at.isoformat(),
        "expires_at": assignment.expires_at.isoformat() if assignment.expires_at else None,
    } for role, assignment in rows]


def _user_payload(db: Session, user: User) -> dict:
    emails = db.scalars(
        select(EmailAddress).where(
            EmailAddress.user_id == user.id,
            EmailAddress.disabled_at.is_(None),
        ).order_by(EmailAddress.is_primary.desc(), EmailAddress.created_at.asc())
    ).all()
    return {
        "id": user.id,
        "display_name": user.display_name,
        "status": user.status,
        "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "emails": [{
            "email": item.email_display,
            "verified": item.verified_at is not None,
            "primary": item.is_primary,
        } for item in emails],
        "roles": _active_roles(db, user.id),
    }


@router.get("/users")
def list_users(
    q: str | None = Query(default=None, max_length=320),
    status: Literal["pending", "active", "suspended", "closed"] | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _actor: User = Depends(_require_permission("users.read")),
    db: Session = Depends(get_db),
) -> dict:
    filters = []
    if status:
        filters.append(User.status == status)
    if q and q.strip():
        term = f"%{q.strip()}%"
        matching_email_ids = select(EmailAddress.user_id).where(
            EmailAddress.disabled_at.is_(None),
            EmailAddress.email_normalized.ilike(term),
        )
        filters.append(or_(
            User.display_name.ilike(term),
            User.id.ilike(term),
            User.id.in_(matching_email_ids),
        ))
    total = db.scalar(select(func.count(User.id)).where(*filters)) or 0
    users = db.scalars(
        select(User).where(*filters)
        .order_by(User.created_at.desc(), User.id)
        .limit(limit).offset(offset)
    ).all()
    return {
        "items": [_user_payload(db, user) for user in users],
        "total": total, "limit": limit, "offset": offset,
    }


@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    _actor: User = Depends(_require_permission("users.read")),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    payload = _user_payload(db, user)
    payload["is_super_admin"] = _is_super_admin(db, user.id)
    payload["active_sessions"] = db.scalar(
        select(func.count(UserSession.id)).where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > utc_now(),
        )
    ) or 0
    return payload


@router.get("/roles")
def list_assignable_roles(
    actor: User = Depends(_require_permission("roles.assign")),
    db: Session = Depends(get_db),
) -> dict:
    super_admin = _is_super_admin(db, actor.id)
    roles = db.scalars(select(Role).order_by(Role.name, Role.code)).all()
    items = []
    for role in roles:
        if role.code == "super_admin" or (role.code == "admin" and not super_admin):
            continue
        permissions = db.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
            .order_by(Permission.code)
        ).all()
        items.append({
            "id": role.id, "code": role.code, "name": role.name,
            "description": role.description, "is_system": role.is_system,
            "permissions": list(permissions),
        })
    return {"items": items}


@router.post("/users/{user_id}/roles", status_code=201)
def post_user_role(
    user_id: str,
    body: RoleAssignmentRequest,
    request: Request,
    actor: User = Depends(_require_permission("roles.assign")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty reason is required.")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.status != "active":
        raise HTTPException(status_code=409, detail="Roles can only be assigned to active users.")
    role = db.get(Role, body.role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found.")
    actor_is_super = _is_super_admin(db, actor.id)
    if role.code == "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin is managed only by one-time bootstrap.")
    if role.code == "admin" and not actor_is_super:
        raise HTTPException(status_code=403, detail="Only a Super Admin can assign the Administrator role.")
    if _is_super_admin(db, target.id):
        raise HTTPException(status_code=403, detail="Super Admin accounts cannot be changed here.")
    try:
        assignment = assign_role(
            db, user_id=target.id, role_id=role.id,
            assigned_by_user_id=actor.id, reason=reason,
        )
        db.add(AuditEvent(
            actor_user_id=actor.id, action="admin.user.role_assignment_reason",
            target_type="user_role", target_id=assignment.id,
            result="success", event_metadata={"role": role.code, "reason": reason},
        ))
        db.commit()
    except AccountServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=exc.code) from exc
    return {"user": _user_payload(db, target), "role": role.code}


@router.post("/users/{user_id}/roles/{role_id}/revoke")
def post_revoke_user_role(
    user_id: str,
    role_id: str,
    body: RoleRevokeRequest,
    request: Request,
    actor: User = Depends(_require_permission("roles.assign")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty reason is required.")
    target = db.get(User, user_id)
    role = db.get(Role, role_id)
    if target is None or role is None:
        raise HTTPException(status_code=404, detail="User or role not found.")
    if role.code == "super_admin" or _is_super_admin(db, target.id):
        raise HTTPException(status_code=403, detail="Super Admin accounts and roles cannot be changed here.")
    if role.code == "admin" and not _is_super_admin(db, actor.id):
        raise HTTPException(status_code=403, detail="Only a Super Admin can revoke the Administrator role.")
    try:
        changed = revoke_role(
            db, user_id=target.id, role_id=role.id,
            revoked_by_user_id=actor.id, reason=reason,
        )
        if changed:
            db.add(AuditEvent(
                actor_user_id=actor.id, action="admin.user.role_revocation_reason",
                target_type="user", target_id=target.id,
                result="success", event_metadata={"role": role.code, "reason": reason},
            ))
        db.commit()
    except AccountServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=exc.code) from exc
    return {"revoked": changed, "user": _user_payload(db, target)}


@router.patch("/users/{user_id}/status")
def patch_user_status(
    user_id: str,
    body: UserStatusRequest,
    request: Request,
    actor: User = Depends(_require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty reason is required.")
    target = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.id == actor.id and body.status == "suspended":
        raise HTTPException(status_code=409, detail="You cannot suspend your own account.")
    if _is_super_admin(db, target.id):
        raise HTTPException(status_code=403, detail="Super Admin accounts cannot be suspended here.")
    target_is_admin = db.scalar(
        select(UserRole.id).join(Role, Role.id == UserRole.role_id).where(
            UserRole.user_id == target.id, Role.code == "admin",
            UserRole.revoked_at.is_(None),
            or_(UserRole.expires_at.is_(None), UserRole.expires_at > utc_now()),
        ).limit(1)
    ) is not None
    if target_is_admin and not _is_super_admin(db, actor.id):
        raise HTTPException(status_code=403, detail="Only a Super Admin can suspend an Administrator.")
    if target.status not in {"active", "suspended"}:
        raise HTTPException(status_code=409, detail="Only active or suspended accounts can change status.")
    if target.status == body.status:
        raise HTTPException(status_code=409, detail="User already has this status.")
    old_status = target.status
    target.status = body.status
    if body.status == "suspended":
        now = utc_now()
        sessions = db.scalars(select(UserSession).where(
            UserSession.user_id == target.id,
            UserSession.revoked_at.is_(None),
        ).with_for_update()).all()
        for session in sessions:
            session.revoked_at = now
            session.revoke_reason = "account_suspended"
    db.add(AuditEvent(
        actor_user_id=actor.id,
        action="admin.user.suspended" if body.status == "suspended" else "admin.user.reactivated",
        target_type="user", target_id=target.id, result="success",
        event_metadata={"old_status": old_status, "new_status": body.status, "reason": reason},
    ))
    db.commit()
    return _user_payload(db, target)

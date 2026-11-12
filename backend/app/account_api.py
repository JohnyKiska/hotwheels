"""Versioned account API: invite acceptance, sessions and email verification."""
from __future__ import annotations

import os
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .account_notifications import (
    create_email_verification_and_queue_email,
    create_invitation_and_queue_email,
)
from .account_services import (
    AccountServiceError,
    accept_invitation,
    authenticate_session,
    consume_email_verification,
    create_session,
    revoke_session,
)
from .db import get_db
from .email_delivery import EmailOutboxError
from .models import (
    EmailAddress,
    Permission,
    RolePermission,
    User,
    UserRole,
    utc_now,
)


router = APIRouter(prefix="/api/v1/account", tags=["accounts"])
SESSION_COOKIE = "hw_session"
CSRF_COOKIE = "hw_csrf"


class InvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role_id: str | None = Field(default=None, max_length=36)
    recipient_name: str | None = Field(default=None, max_length=240)


class InvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)
    display_name: str | None = Field(default=None, max_length=240)


class EmailVerificationRequest(BaseModel):
    pass


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)


def _cookie_secure() -> bool:
    return os.environ.get("HW_COOKIE_SECURE", "true").strip().lower() not in {
        "0", "false", "no"
    }


def _public_base_url() -> str:
    value = os.environ.get("HW_PUBLIC_BASE_URL", "").strip().rstrip("/")
    parsed = urlsplit(value)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if (parsed.scheme != "https" and not local_http) or not parsed.netloc:
        raise HTTPException(status_code=503, detail="Account email delivery is not configured.")
    return value


def _allowed_origins() -> set[str]:
    configured = os.environ.get("HW_ALLOWED_ORIGINS", "").strip()
    if configured:
        return {item.strip().rstrip("/") for item in configured.split(",") if item.strip()}
    try:
        return {_public_base_url()}
    except HTTPException:
        return set()


def _require_csrf(request: Request) -> None:
    origin = request.headers.get("origin", "").rstrip("/")
    csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
    csrf_header = request.headers.get("x-csrf-token", "")
    if (
        not origin
        or origin not in _allowed_origins()
        or not csrf_cookie
        or not csrf_header
        or not secrets.compare_digest(csrf_cookie, csrf_header)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")


def _current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    authenticated = authenticate_session(db, raw_token)
    if authenticated is None:
        db.commit()
        raise HTTPException(status_code=401, detail="Session is invalid or expired.")
    return authenticated[1]


def _has_permission(db: Session, user_id: str, permission_code: str) -> bool:
    now = utc_now()
    permission_id = db.scalar(
        select(Permission.id)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
            or_(UserRole.expires_at.is_(None), UserRole.expires_at > now),
            Permission.code == permission_code,
        )
        .limit(1)
    )
    return permission_id is not None


def _require_permission(permission_code: str):
    def dependency(
        user: User = Depends(_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not _has_permission(db, user.id, permission_code):
            raise HTTPException(status_code=403, detail="Insufficient permission.")
        return user
    return dependency


def _set_session_cookies(response: Response, raw_token: str, lifetime_seconds: int) -> None:
    secure = _cookie_secure()
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=max(1, lifetime_seconds),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max(1, lifetime_seconds),
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    secure = _cookie_secure()
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax")


@router.get("/me")
def get_account_me(
    user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> dict:
    roles = db.scalars(
        select(UserRole.role_id).where(
            UserRole.user_id == user.id,
            UserRole.revoked_at.is_(None),
            or_(UserRole.expires_at.is_(None), UserRole.expires_at > utc_now()),
        )
    ).all()
    db.commit()
    return {
        "id": user.id,
        "status": user.status,
        "display_name": user.display_name,
        "role_ids": list(roles),
    }


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> Response:
    _require_csrf(request)
    raw_token = request.cookies.get(SESSION_COOKIE, "")
    revoke_session(db, raw_token, actor_user_id=user.id, reason="logout")
    db.commit()
    _clear_session_cookies(response)
    response.status_code = 204
    return response


@router.post("/invitations", status_code=201)
def create_account_invitation(
    request: Request,
    body: InvitationCreateRequest,
    user: User = Depends(_require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    if body.role_id and not _has_permission(db, user.id, "roles.assign"):
        raise HTTPException(status_code=403, detail="Insufficient permission to assign roles.")
    try:
        invitation = create_invitation_and_queue_email(
            db,
            email=body.email,
            invited_by_user_id=user.id,
            role_id=body.role_id,
            recipient_name=body.recipient_name,
            public_base_url=_public_base_url(),
        )
        db.commit()
    except AccountServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=exc.code) from exc
    except (EmailOutboxError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to queue invitation email.") from exc
    return {
        "id": invitation.id,
        "email": invitation.email_normalized,
        "status": invitation.status,
        "expires_at": invitation.expires_at.isoformat(),
    }


@router.post("/invitations/accept", status_code=201)
def accept_account_invitation(
    body: InvitationAcceptRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    try:
        user, email = accept_invitation(db, body.token, display_name=body.display_name)
        session, raw_session_token = create_session(db, user_id=user.id)
        db.commit()
    except AccountServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=exc.code) from exc

    lifetime = int((session.expires_at - utc_now()).total_seconds())
    _set_session_cookies(response, raw_session_token, lifetime)
    return {
        "user": {
            "id": user.id,
            "status": user.status,
            "display_name": user.display_name,
        },
        "email": email.email_normalized,
        "email_verified": email.verified_at is not None,
    }


@router.post("/email-verification/request", status_code=202)
def request_email_verification(
    request: Request,
    user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    email = db.scalar(select(EmailAddress).where(
        EmailAddress.user_id == user.id,
        EmailAddress.is_primary.is_(True),
        EmailAddress.disabled_at.is_(None),
    ))
    if email is None:
        raise HTTPException(status_code=404, detail="Primary email address not found.")
    if email.verified_at is not None:
        raise HTTPException(status_code=409, detail="Email address is already verified.")
    try:
        create_email_verification_and_queue_email(
            db,
            email_address_id=email.id,
            public_base_url=_public_base_url(),
        )
        db.commit()
    except (AccountServiceError, EmailOutboxError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to queue verification email.") from exc
    return {"status": "queued"}


@router.post("/email-verification/confirm")
def confirm_email_verification(
    body: EmailVerificationConfirmRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        email = consume_email_verification(db, body.token)
        db.commit()
    except AccountServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=exc.code) from exc
    return {"email": email.email_normalized, "verified": True}

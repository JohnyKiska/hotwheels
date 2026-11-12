"""Email/password authentication, reset workflow and persistent throttling."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .account_api import (
    _current_user,
    _public_base_url,
    _require_csrf,
    _set_session_cookies,
)
from .account_services import (
    AccountServiceError,
    create_session,
    normalize_email,
)
from .db import get_db
from .email_delivery import EmailOutboxError, queue_email
from .models import (
    AuditEvent,
    AuthRateLimitBucket,
    EmailAddress,
    PasswordCredential,
    PasswordResetToken,
    User,
    UserSession,
    utc_now,
)


router = APIRouter(prefix="/api/v1/account/password", tags=["account-password"])
PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19_456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
# A real Argon2id hash makes unknown-email login attempts pay the same
# password-verification cost as known-email attempts.
_DUMMY_HASH = PASSWORD_HASHER.hash("not-a-real-user-password")
_LOGIN_WINDOW = timedelta(minutes=15)
_LOCK_DURATION = timedelta(minutes=15)
_RESET_LIFETIME = timedelta(minutes=30)


class PasswordLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class PasswordSetRequest(BaseModel):
    password: str = Field(min_length=12, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)
    password: str = Field(min_length=12, max_length=128)


def _rate_secret() -> bytes:
    value = os.environ.get("HW_AUTH_RATE_LIMIT_KEY", "")
    if len(value) < 32:
        raise HTTPException(
            status_code=503,
            detail="Authentication protection is not configured.",
        )
    return value.encode("utf-8")


def _bucket_key(kind: str, value: str) -> str:
    digest = hmac.new(
        _rate_secret(),
        f"{kind}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def _client_ip(request: Request) -> str:
    # Do not trust X-Forwarded-For unless a separately configured trusted-proxy
    # middleware has validated it.
    return request.client.host if request.client else "unknown"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _blocked(db: Session, keys: list[str], now: datetime) -> bool:
    if not keys:
        return False
    rows = db.scalars(
        select(AuthRateLimitBucket).where(AuthRateLimitBucket.bucket_key.in_(keys))
    ).all()
    return any(
        row.blocked_until is not None and _aware(row.blocked_until) > now
        for row in rows
    )


def _record_failure(
    db: Session,
    key: str,
    *,
    now: datetime,
    threshold: int,
) -> None:
    reset_at = now - _LOGIN_WINDOW
    attempts = case(
        (AuthRateLimitBucket.window_started_at < reset_at, 1),
        else_=AuthRateLimitBucket.attempts + 1,
    )
    window_start = case(
        (AuthRateLimitBucket.window_started_at < reset_at, now),
        else_=AuthRateLimitBucket.window_started_at,
    )
    blocked_until = case(
        (attempts >= threshold, now + _LOCK_DURATION),
        (AuthRateLimitBucket.window_started_at < reset_at, None),
        else_=AuthRateLimitBucket.blocked_until,
    )
    values = {
        "bucket_key": key,
        "window_started_at": now,
        "attempts": 1,
        "blocked_until": None,
        "updated_at": now,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        statement = sqlite_insert(AuthRateLimitBucket).values(**values)
    elif dialect == "postgresql":
        statement = pg_insert(AuthRateLimitBucket).values(**values)
    else:
        raise HTTPException(status_code=503, detail="Authentication protection is unavailable.")
    statement = statement.on_conflict_do_update(
        index_elements=[AuthRateLimitBucket.bucket_key],
        set_={
            "window_started_at": window_start,
            "attempts": attempts,
            "blocked_until": blocked_until,
            "updated_at": now,
        },
    )
    db.execute(statement)


def _clear_email_failures(db: Session, email_key: str) -> None:
    db.execute(
        delete(AuthRateLimitBucket).where(
            AuthRateLimitBucket.bucket_key == email_key
        )
    )


def _audit(
    db: Session,
    action: str,
    *,
    user_id: str | None = None,
    result: str = "success",
    metadata: dict | None = None,
) -> None:
    db.add(AuditEvent(
        actor_user_id=user_id,
        action=action,
        target_type="user" if user_id else None,
        target_id=user_id,
        result=result,
        event_metadata=metadata or {},
    ))


def _hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 128 or not password.strip():
        raise HTTPException(
            status_code=422,
            detail="Password must contain 12 to 128 characters.",
        )
    return PASSWORD_HASHER.hash(password)


def _verify_password(encoded: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(encoded, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, TypeError):
        return False


def _generic_login_error() -> HTTPException:
    return HTTPException(status_code=401, detail="Invalid email or password.")


@router.post("/login")
def password_login(
    body: PasswordLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    now = utc_now()
    normalized = body.email.strip().casefold()
    if len(normalized) > 320 or normalized.count("@") != 1:
        normalized = "invalid"
    email_key = _bucket_key("email", normalized)
    ip_key = _bucket_key("ip", _client_ip(request))
    if _blocked(db, [email_key, ip_key], now):
        db.commit()
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    email = db.scalar(
        select(EmailAddress).where(
            EmailAddress.email_normalized == normalized,
            EmailAddress.is_primary.is_(True),
            EmailAddress.verified_at.is_not(None),
            EmailAddress.disabled_at.is_(None),
        )
    )
    user = db.get(User, email.user_id) if email else None
    credential = db.scalar(
        select(PasswordCredential).where(
            PasswordCredential.user_id == user.id,
            PasswordCredential.disabled_at.is_(None),
        )
    ) if user else None

    encoded = credential.password_hash if credential else _DUMMY_HASH
    valid_password = _verify_password(encoded, body.password)
    if (
        not valid_password
        or user is None
        or user.status != "active"
        or credential is None
    ):
        _record_failure(db, email_key, now=now, threshold=5)
        _record_failure(db, ip_key, now=now, threshold=12)
        _audit(db, "auth.password.login", result="failure")
        db.commit()
        raise _generic_login_error()

    _clear_email_failures(db, email_key)
    if PASSWORD_HASHER.check_needs_rehash(credential.password_hash):
        credential.password_hash = PASSWORD_HASHER.hash(body.password)
        credential.changed_at = now
    session, raw_token = create_session(
        db,
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
    )
    _audit(db, "auth.password.login", user_id=user.id)
    db.commit()
    lifetime = max(1, int((_aware(session.expires_at) - utc_now()).total_seconds()))
    _set_session_cookies(response, raw_token, lifetime)
    return {
        "user": {
            "id": user.id,
            "status": user.status,
            "display_name": user.display_name,
        }
    }


@router.post("/set")
def set_password(
    body: PasswordSetRequest,
    request: Request,
    user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    email = db.scalar(
        select(EmailAddress).where(
            EmailAddress.user_id == user.id,
            EmailAddress.is_primary.is_(True),
            EmailAddress.verified_at.is_not(None),
            EmailAddress.disabled_at.is_(None),
        )
    )
    if email is None:
        raise HTTPException(status_code=403, detail="A verified primary email is required.")
    existing = db.scalar(
        select(PasswordCredential).where(PasswordCredential.user_id == user.id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A password is already configured.")
    db.add(PasswordCredential(
        user_id=user.id,
        password_hash=_hash_password(body.password),
        password_hash_algorithm="argon2id",
        changed_at=utc_now(),
    ))
    _audit(db, "auth.password.created", user_id=user.id)
    db.commit()
    return {"status": "password_configured"}


@router.post("/change")
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Change a password after verifying the current one; keep only this session."""
    _require_csrf(request)
    now = utc_now()
    user_key = _bucket_key("password-change-user", user.id)
    ip_key = _bucket_key("password-change-ip", _client_ip(request))
    if _blocked(db, [user_key, ip_key], now):
        db.commit()
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    credential = db.scalar(
        select(PasswordCredential)
        .where(
            PasswordCredential.user_id == user.id,
            PasswordCredential.disabled_at.is_(None),
        )
        .with_for_update()
    )
    if credential is None or not _verify_password(
        credential.password_hash, body.current_password
    ):
        _record_failure(db, user_key, now=now, threshold=5)
        _record_failure(db, ip_key, now=now, threshold=12)
        _audit(db, "auth.password.change", user_id=user.id, result="failure")
        db.commit()
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    new_hash = _hash_password(body.new_password)
    raw_session = request.cookies.get("hw_session", "")
    if not raw_session:
        db.rollback()
        raise HTTPException(status_code=401, detail="Authentication required.")
    current_session_hash = hashlib.sha256(raw_session.encode("utf-8")).hexdigest()

    credential.password_hash = new_hash
    credential.password_hash_algorithm = "argon2id"
    credential.changed_at = now
    db.execute(
        UserSession.__table__.update()
        .where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.token_hash != current_session_hash,
        )
        .values(revoked_at=now, revoke_reason="password_changed")
    )
    db.execute(update_reset_tokens_statement(user.id, now))
    db.execute(
        delete(AuthRateLimitBucket).where(
            AuthRateLimitBucket.bucket_key.in_([user_key, ip_key])
        )
    )
    _audit(db, "auth.password.changed", user_id=user.id)
    db.commit()
    return {"status": "password_changed"}


@router.post("/reset/request", status_code=202)
def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    now = utc_now()
    try:
        normalized = normalize_email(body.email)
    except AccountServiceError:
        normalized = "invalid"
    email_key = _bucket_key("reset-email", normalized)
    ip_key = _bucket_key("reset-ip", _client_ip(request))
    if _blocked(db, [email_key, ip_key], now):
        db.commit()
        return {"status": "if_account_is_eligible_email_will_be_sent"}

    email = db.scalar(
        select(EmailAddress).where(
            EmailAddress.email_normalized == normalized,
            EmailAddress.is_primary.is_(True),
            EmailAddress.verified_at.is_not(None),
            EmailAddress.disabled_at.is_(None),
        )
    )
    user = db.get(User, email.user_id) if email else None
    credential = db.scalar(
        select(PasswordCredential).where(
            PasswordCredential.user_id == user.id,
            PasswordCredential.disabled_at.is_(None),
        )
    ) if user else None

    if user and user.status == "active" and email and credential:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + _RESET_LIFETIME,
        )
        db.add(token)
        db.flush()
        base = os.environ.get("HW_FRONTEND_URL", "").strip().rstrip("/") or _public_base_url()
        link = f"{base}/login.html?reset={quote(raw_token, safe='')}"
        queue_email(
            db,
            recipient=email.email_normalized,
            subject="Сброс пароля HW Catalog",
            text_body=(
                "Для сброса пароля HW Catalog откройте ссылку: "
                f"{link}\n\nСсылка одноразовая и действует 30 минут. "
                "Если вы не запрашивали сброс, проигнорируйте это письмо."
            ),
            html_body=(
                "<p>Для сброса пароля HW Catalog перейдите по ссылке:</p>"
                f'<p><a href="{link}">Сбросить пароль</a></p>'
                "<p>Ссылка одноразовая и действует 30 минут. "
                "Если вы не запрашивали сброс, проигнорируйте это письмо.</p>"
            ),
            idempotency_key=f"password-reset:{token.id}",
        )
        _audit(db, "auth.password.reset_requested", user_id=user.id)
    _record_failure(db, email_key, now=now, threshold=3)
    _record_failure(db, ip_key, now=now, threshold=12)
    db.commit()
    return {"status": "if_account_is_eligible_email_will_be_sent"}


@router.post("/reset/confirm")
def confirm_password_reset(
    body: PasswordResetConfirmRequest,
    db: Session = Depends(get_db),
) -> dict:
    if len(body.token) > 256:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
    digest = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    token = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == digest
        ).with_for_update()
    )
    now = utc_now()
    if (
        token is None
        or token.consumed_at is not None
        or _aware(token.expires_at) <= now
    ):
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")

    user = db.scalar(select(User).where(User.id == token.user_id).with_for_update())
    credential = db.scalar(
        select(PasswordCredential).where(
            PasswordCredential.user_id == token.user_id
        ).with_for_update()
    )
    if user is None or user.status != "active" or credential is None:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")

    credential.password_hash = _hash_password(body.password)
    credential.password_hash_algorithm = "argon2id"
    credential.changed_at = now
    token.consumed_at = now
    db.execute(
        update_reset_tokens_statement(token.user_id, now)
    )
    db.execute(
        UserSession.__table__.update()
        .where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason="password_reset")
    )
    _audit(db, "auth.password.reset_completed", user_id=user.id)
    db.commit()
    return {"status": "password_reset"}


def update_reset_tokens_statement(user_id: str, now: datetime):
    return (
        PasswordResetToken.__table__.update()
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )

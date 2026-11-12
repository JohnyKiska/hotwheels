"""Transactional account/authentication services.

The caller owns the SQLAlchemy transaction and must commit or roll back.
Raw bearer tokens are returned only once and are never persisted or audited.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AuditEvent,
    EmailAddress,
    EmailVerificationToken,
    Invitation,
    Role,
    User,
    UserRole,
    UserSession,
    utc_now,
)


class AccountServiceError(ValueError):
    """Expected account workflow failure with a stable machine-readable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def normalize_email(email: str) -> str:
    value = email.strip().casefold()
    if not value or len(value) > 320 or value.count("@") != 1:
        raise AccountServiceError("invalid_email")
    local, domain = value.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        raise AccountServiceError("invalid_email")
    return value


def _token_pair() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, digest


def _aware(value: datetime) -> datetime:
    """SQLite may return naive datetimes for timezone-aware columns."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _audit(
    db: Session,
    action: str,
    *,
    actor_user_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    result: str = "success",
    metadata: dict | None = None,
) -> None:
    db.add(AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        event_metadata=metadata or {},
    ))


def create_user(
    db: Session,
    *,
    display_name: str | None = None,
    status: str = "pending",
) -> User:
    if status not in {"pending", "active"}:
        raise AccountServiceError("invalid_initial_user_status")
    user = User(status=status, display_name=display_name)
    db.add(user)
    db.flush()
    _audit(db, "user.created", target_type="user", target_id=user.id,
           metadata={"status": status})
    return user


def link_external_identity(
    db: Session,
    *,
    user_id: str,
    provider: str,
    issuer: str,
    provider_subject: str,
    provider_username: str | None = None,
    provider_email: str | None = None,
) :
    """Link an already-authenticated provider subject; never match by email."""
    from .models import ExternalIdentity

    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.status != "active":
        raise AccountServiceError("user_not_active")
    if provider not in {"github", "google"} or not issuer or not provider_subject:
        raise AccountServiceError("invalid_external_identity")
    existing = db.scalar(select(ExternalIdentity).where(
        ExternalIdentity.issuer == issuer,
        ExternalIdentity.provider_subject == provider_subject,
    ))
    if existing is not None:
        if existing.user_id == user_id and existing.disabled_at is None:
            return existing
        raise AccountServiceError("identity_already_linked")
    identity = ExternalIdentity(
        user_id=user_id,
        provider=provider,
        issuer=issuer,
        provider_subject=provider_subject,
        provider_username=provider_username,
        provider_email=provider_email,
        last_authenticated_at=utc_now(),
    )
    db.add(identity)
    db.flush()
    _audit(db, "user.identity.linked", actor_user_id=user_id,
           target_type="external_identity", target_id=identity.id,
           metadata={"provider": provider, "issuer": issuer})
    return identity


def assign_role(
    db: Session,
    *,
    user_id: str,
    role_id: str,
    assigned_by_user_id: str | None = None,
) -> UserRole:
    """Assign a role idempotently while retaining historical revoked rows."""
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.status != "active":
        raise AccountServiceError("user_not_active")
    role = db.get(Role, role_id)
    if role is None:
        raise AccountServiceError("role_not_found")
    if role.code == "super_admin":
        raise AccountServiceError("super_admin_requires_bootstrap")
    now = utc_now()
    active = db.scalar(select(UserRole).where(
        UserRole.user_id == user_id,
        UserRole.role_id == role_id,
        UserRole.revoked_at.is_(None),
        (UserRole.expires_at.is_(None)) | (UserRole.expires_at > now),
    ).with_for_update())
    if active is not None:
        return active
    assignment = UserRole(
        user_id=user_id,
        role_id=role_id,
        assigned_by_user_id=assigned_by_user_id,
        assigned_at=now,
    )
    db.add(assignment)
    db.flush()
    _audit(db, "user.role.assigned", actor_user_id=assigned_by_user_id,
           target_type="user", target_id=user_id, metadata={"role": role.code})
    return assignment


def revoke_role(
    db: Session,
    *,
    user_id: str,
    role_id: str,
    revoked_by_user_id: str | None = None,
) -> bool:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise AccountServiceError("user_not_found")
    role = db.get(Role, role_id)
    if role is None:
        raise AccountServiceError("role_not_found")
    if role.code == "super_admin":
        raise AccountServiceError("super_admin_requires_bootstrap")
    assignment = db.scalar(select(UserRole).where(
        UserRole.user_id == user_id,
        UserRole.role_id == role_id,
        UserRole.revoked_at.is_(None),
    ).with_for_update())
    if assignment is None:
        return False
    assignment.revoked_at = utc_now()
    assignment.revoked_by_user_id = revoked_by_user_id
    db.flush()
    _audit(db, "user.role.revoked", actor_user_id=revoked_by_user_id,
           target_type="user", target_id=user_id,
           metadata={"role": role.code if role else "unknown"})
    return True


def create_session(
    db: Session,
    *,
    user_id: str,
    lifetime: timedelta = timedelta(days=14),
    user_agent: str | None = None,
) -> tuple[UserSession, str]:
    if lifetime <= timedelta(0) or lifetime > timedelta(days=90):
        raise AccountServiceError("invalid_session_lifetime")
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.status != "active":
        raise AccountServiceError("user_not_active")
    raw, digest = _token_pair()
    now = utc_now()
    session = UserSession(
        user_id=user_id,
        token_hash=digest,
        created_at=now,
        expires_at=now + lifetime,
        user_agent=user_agent[:500] if user_agent else None,
    )
    user.last_login_at = now
    db.add(session)
    db.flush()
    _audit(db, "auth.session.created", actor_user_id=user_id,
           target_type="session", target_id=session.id)
    return session, raw


def authenticate_session(
    db: Session,
    raw_token: str,
    *,
    touch_interval: timedelta = timedelta(minutes=5),
) -> tuple[UserSession, User] | None:
    if not raw_token or len(raw_token) > 256:
        return None
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    session = db.scalar(select(UserSession).where(
        UserSession.token_hash == digest
    ).with_for_update())
    if session is None or session.revoked_at is not None:
        return None
    now = utc_now()
    if _aware(session.expires_at) <= now:
        session.revoked_at = now
        session.revoke_reason = "expired"
        _audit(db, "auth.session.expired", actor_user_id=session.user_id,
               target_type="session", target_id=session.id)
        db.flush()
        return None
    user = db.get(User, session.user_id)
    if user is None or user.status != "active":
        return None
    if session.last_seen_at is None or now - _aware(session.last_seen_at) >= touch_interval:
        session.last_seen_at = now
        db.flush()
    return session, user


def revoke_session(
    db: Session,
    raw_token: str,
    *,
    actor_user_id: str | None = None,
    reason: str = "logout",
) -> bool:
    if not raw_token or len(raw_token) > 256:
        return False
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    session = db.scalar(select(UserSession).where(
        UserSession.token_hash == digest
    ).with_for_update())
    if session is None or session.revoked_at is not None:
        return False
    session.revoked_at = utc_now()
    session.revoke_reason = reason[:120]
    db.flush()
    _audit(db, "auth.session.revoked", actor_user_id=actor_user_id or session.user_id,
           target_type="session", target_id=session.id,
           metadata={"reason": reason[:120]})
    return True


def create_invitation(
    db: Session,
    *,
    email: str,
    invited_by_user_id: str,
    role_id: str | None = None,
    lifetime: timedelta = timedelta(days=7),
) -> tuple[Invitation, str]:
    normalized = normalize_email(email)
    if lifetime <= timedelta(0) or lifetime > timedelta(days=30):
        raise AccountServiceError("invalid_invitation_lifetime")
    inviter = db.get(User, invited_by_user_id)
    if inviter is None or inviter.status != "active":
        raise AccountServiceError("inviter_not_active")
    if role_id is not None:
        role = db.get(Role, role_id)
        if role is None:
            raise AccountServiceError("role_not_found")
        if role.code == "super_admin":
            raise AccountServiceError("super_admin_cannot_be_invited")
    pending = db.scalar(select(Invitation).where(
        Invitation.email_normalized == normalized,
        Invitation.status == "pending",
    ).with_for_update())
    if pending is not None and _aware(pending.expires_at) > utc_now():
        raise AccountServiceError("pending_invitation_exists")
    if pending is not None:
        pending.status = "expired"
    raw, digest = _token_pair()
    invitation = Invitation(
        email_normalized=normalized,
        token_hash=digest,
        invited_by_user_id=invited_by_user_id,
        role_id=role_id,
        status="pending",
        expires_at=utc_now() + lifetime,
    )
    db.add(invitation)
    db.flush()
    _audit(db, "invitation.created", actor_user_id=invited_by_user_id,
           target_type="invitation", target_id=invitation.id,
           metadata={"email": normalized, "role_id": role_id})
    return invitation, raw


def accept_invitation(
    db: Session,
    raw_token: str,
    *,
    display_name: str | None = None,
) -> tuple[User, EmailAddress]:
    if not raw_token or len(raw_token) > 256:
        raise AccountServiceError("invalid_invitation")
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    invitation = db.scalar(select(Invitation).where(
        Invitation.token_hash == digest
    ).with_for_update())
    now = utc_now()
    if invitation is None or invitation.status != "pending":
        raise AccountServiceError("invalid_invitation")
    if _aware(invitation.expires_at) <= now:
        invitation.status = "expired"
        db.flush()
        raise AccountServiceError("invitation_expired")
    email = db.scalar(select(EmailAddress).where(
        EmailAddress.email_normalized == invitation.email_normalized
    ).with_for_update())
    if email is not None and email.disabled_at is not None:
        raise AccountServiceError("email_unavailable")
    if email is None:
        user = create_user(db, display_name=display_name, status="active")
        email = EmailAddress(
            user_id=user.id,
            email_normalized=invitation.email_normalized,
            email_display=invitation.email_normalized,
            is_primary=True,
            verified_at=now,
        )
        db.add(email)
        db.flush()
    else:
        user = db.scalar(select(User).where(
            User.id == email.user_id
        ).with_for_update())
        if user is None or user.status in {"suspended", "closed"}:
            raise AccountServiceError("user_unavailable")
        email.verified_at = email.verified_at or now
        if user.status == "pending":
            user.status = "active"
        if display_name and not user.display_name:
            user.display_name = display_name
    if invitation.role_id is not None:
        assign_role(
            db, user_id=user.id, role_id=invitation.role_id,
            assigned_by_user_id=invitation.invited_by_user_id,
        )
    invitation.status = "accepted"
    invitation.accepted_by_user_id = user.id
    invitation.accepted_at = now
    db.flush()
    _audit(db, "invitation.accepted", actor_user_id=user.id,
           target_type="invitation", target_id=invitation.id)
    return user, email


def create_email_verification(
    db: Session,
    *,
    email_address_id: str,
    lifetime: timedelta = timedelta(hours=24),
) -> tuple[EmailVerificationToken, str]:
    if lifetime <= timedelta(0) or lifetime > timedelta(days=7):
        raise AccountServiceError("invalid_verification_lifetime")
    email = db.get(EmailAddress, email_address_id)
    if email is None or email.disabled_at is not None:
        raise AccountServiceError("email_unavailable")
    raw, digest = _token_pair()
    token = EmailVerificationToken(
        email_address_id=email_address_id,
        token_hash=digest,
        created_at=utc_now(),
        expires_at=utc_now() + lifetime,
    )
    db.add(token)
    db.flush()
    _audit(db, "auth.email_verification.created",
           target_type="email_address", target_id=email_address_id)
    return token, raw


def consume_email_verification(
    db: Session,
    raw_token: str,
) -> EmailAddress:
    if not raw_token or len(raw_token) > 256:
        raise AccountServiceError("invalid_verification_token")
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    token = db.scalar(select(EmailVerificationToken).where(
        EmailVerificationToken.token_hash == digest
    ).with_for_update())
    now = utc_now()
    if token is None or token.consumed_at is not None:
        raise AccountServiceError("invalid_verification_token")
    if _aware(token.expires_at) <= now:
        raise AccountServiceError("verification_token_expired")
    email = db.scalar(select(EmailAddress).where(
        EmailAddress.id == token.email_address_id
    ).with_for_update())
    if email is None or email.disabled_at is not None:
        raise AccountServiceError("email_unavailable")
    user = db.scalar(select(User).where(User.id == email.user_id).with_for_update())
    if user is None or user.status in {"suspended", "closed"}:
        raise AccountServiceError("user_unavailable")
    token.consumed_at = now
    email.verified_at = email.verified_at or now
    if user.status == "pending":
        user.status = "active"
    db.flush()
    _audit(db, "auth.email_verification.completed",
           actor_user_id=user.id, target_type="email_address", target_id=email.id)
    return email

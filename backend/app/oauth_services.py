"""Secure, database-backed OAuth state and PKCE transaction helpers."""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import OAuthAuthorizationRequest, utc_now


class OAuthFlowError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fernet() -> Fernet:
    key = os.environ.get("HW_OAUTH_ENCRYPTION_KEY", "").strip()
    if not key:
        raise OAuthFlowError("oauth_encryption_key_not_configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise OAuthFlowError("invalid_oauth_encryption_key") from exc


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_oauth_request(
    db: Session,
    *,
    provider: str,
    redirect_uri: str,
    intent: str = "login",
    user_id: str | None = None,
    session_token: str | None = None,
) -> tuple[OAuthAuthorizationRequest, str, str, str | None]:
    if provider not in {"github", "google"} or intent not in {"login", "link"}:
        raise OAuthFlowError("invalid_oauth_request")
    if intent == "link" and (not user_id or not session_token):
        raise OAuthFlowError("authenticated_session_required")
    if intent == "login" and (user_id or session_token):
        raise OAuthFlowError("invalid_oauth_request")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    nonce = secrets.token_urlsafe(32) if provider == "google" else None
    encrypted_verifier = _fernet().encrypt(verifier.encode("ascii")).decode("ascii")
    now = utc_now()
    request = OAuthAuthorizationRequest(
        provider=provider,
        state_hash=digest(state),
        nonce_hash=digest(nonce) if nonce else None,
        code_verifier_encrypted=encrypted_verifier,
        redirect_uri=redirect_uri,
        intent=intent,
        user_id=user_id,
        session_token_hash=digest(session_token) if session_token else None,
        expires_at=now + timedelta(minutes=10),
    )
    db.add(request)
    db.flush()
    return request, state, verifier, nonce


def consume_oauth_request(db: Session, raw_state: str, *, provider: str) -> dict:
    if not raw_state or len(raw_state) > 256:
        raise OAuthFlowError("invalid_oauth_state")
    request = db.scalar(
        select(OAuthAuthorizationRequest)
        .where(
            OAuthAuthorizationRequest.state_hash == digest(raw_state),
            OAuthAuthorizationRequest.provider == provider,
        )
        .with_for_update()
    )
    now = utc_now()
    if request is None or request.consumed_at is not None:
        raise OAuthFlowError("invalid_oauth_state")
    expires_at = request.expires_at
    if expires_at.tzinfo is None:
        from datetime import timezone
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        request.consumed_at = now
        db.flush()
        raise OAuthFlowError("oauth_state_expired")
    try:
        verifier = _fernet().decrypt(
            request.code_verifier_encrypted.encode("ascii")
        ).decode("ascii")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise OAuthFlowError("oauth_verifier_unavailable") from exc
    result = {
        "provider": request.provider,
        "redirect_uri": request.redirect_uri,
        "intent": request.intent,
        "user_id": request.user_id,
        "session_token_hash": request.session_token_hash,
        "nonce_hash": request.nonce_hash,
        "code_verifier": verifier,
    }
    request.consumed_at = now
    db.flush()
    return result

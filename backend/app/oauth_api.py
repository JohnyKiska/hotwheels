"""GitHub OAuth and Google OIDC authorization-code callbacks."""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .account_api import (
    SESSION_COOKIE,
    _cookie_secure,
    _current_user,
    _public_base_url,
    _require_csrf,
    _set_session_cookies,
)
from .account_services import (
    AccountServiceError,
    authenticate_session,
    create_session,
    link_external_identity,
)
from .db import get_db
from .models import ExternalIdentity, User, utc_now
from .oauth_services import (
    OAuthFlowError,
    consume_oauth_request,
    create_oauth_request,
    digest,
)

router = APIRouter(prefix="/api/v1/account/oauth", tags=["account-oauth"])


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="OAuth provider is not configured.")
    return value


def _redirect_uri(provider: str) -> str:
    return _required(f"HW_{provider.upper()}_REDIRECT_URI")


def _frontend_result(status: str) -> RedirectResponse:
    base = os.environ.get("HW_FRONTEND_URL", "").strip().rstrip("/")
    if not base:
        base = _public_base_url()
    return RedirectResponse(
        f"{base}/login?{urlencode({'oauth': status})}",
        status_code=303,
    )



def _state_cookie_name(state: str) -> str:
    return "hw_oauth_state_" + digest(state)[:20]


def _oauth_start_response(provider: str, state: str, url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(
        _state_cookie_name(state),
        state,
        max_age=600,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=f"/api/v1/account/oauth/{provider}/callback",
    )
    return response


def _oauth_finish(provider: str, state: str, status: str) -> RedirectResponse:
    response = _frontend_result(status)
    response.delete_cookie(
        _state_cookie_name(state),
        path=f"/api/v1/account/oauth/{provider}/callback",
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
    )
    return response

def _pkce_challenge(verifier: str) -> str:
    digest_bytes = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest_bytes).rstrip(b"=").decode("ascii")


def _authorization_url(provider: str, state: str, verifier: str, nonce: str | None,
                        redirect_uri: str) -> str:
    challenge = _pkce_challenge(verifier)
    if provider == "github":
        params = {
            "client_id": _required("HW_GITHUB_CLIENT_ID"),
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return "https://github.com/login/oauth/authorize?" + urlencode(params)

    params = {
        "client_id": _required("HW_GOOGLE_CLIENT_ID"),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce or "",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


@router.get("/{provider}/start")
def start_oauth_login(provider: str, db: Session = Depends(get_db)):
    if provider not in {"github", "google"}:
        raise HTTPException(status_code=404, detail="OAuth provider not found.")
    redirect_uri = _redirect_uri(provider)
    # Fail before creating a state record if required client configuration is absent.
    _required(f"HW_{provider.upper()}_CLIENT_ID")
    _required(f"HW_{provider.upper()}_CLIENT_SECRET")
    try:
        _request, state, verifier, nonce = create_oauth_request(
            db, provider=provider, redirect_uri=redirect_uri
        )
        url = _authorization_url(provider, state, verifier, nonce, redirect_uri)
        db.commit()
    except OAuthFlowError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=exc.code) from exc
    return _oauth_start_response(provider, state, url)


@router.post("/{provider}/link")
def start_oauth_link(
    provider: str,
    request: Request,
    user: User = Depends(_current_user),
    db: Session = Depends(get_db),
):
    if provider not in {"github", "google"}:
        raise HTTPException(status_code=404, detail="OAuth provider not found.")
    _require_csrf(request)
    redirect_uri = _redirect_uri(provider)
    _required(f"HW_{provider.upper()}_CLIENT_ID")
    _required(f"HW_{provider.upper()}_CLIENT_SECRET")
    raw_session = request.cookies.get(SESSION_COOKIE, "")
    try:
        _request, state, verifier, nonce = create_oauth_request(
            db,
            provider=provider,
            redirect_uri=redirect_uri,
            intent="link",
            user_id=user.id,
            session_token=raw_session,
        )
        url = _authorization_url(provider, state, verifier, nonce, redirect_uri)
        db.commit()
    except OAuthFlowError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=exc.code) from exc
    return _oauth_start_response(provider, state, url)


def _github_profile(code: str, redirect_uri: str, verifier: str) -> dict:
    client_id = _required("HW_GITHUB_CLIENT_ID")
    client_secret = _required("HW_GITHUB_CLIENT_SECRET")
    with httpx.Client(timeout=15) as client:
        token_response = client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("github_token_exchange_failed")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        profile_response = client.get("https://api.github.com/user", headers=headers)
        profile_response.raise_for_status()
        profile = profile_response.json()
        subject = profile.get("id")
        if not isinstance(subject, int) or subject <= 0:
            raise ValueError("github_subject_missing")
        email = profile.get("email") if isinstance(profile.get("email"), str) else None
        if not email:
            emails_response = client.get("https://api.github.com/user/emails", headers=headers)
            emails_response.raise_for_status()
            emails = emails_response.json()
            if isinstance(emails, list):
                primary = next(
                    (item for item in emails
                     if isinstance(item, dict) and item.get("primary") is True
                     and item.get("verified") is True and isinstance(item.get("email"), str)),
                    None,
                )
                email = primary["email"] if primary else None
        return {
            "issuer": "https://github.com",
            "subject": str(subject),
            "username": profile.get("login") if isinstance(profile.get("login"), str) else None,
            "email": email,
            "display_name": profile.get("name") if isinstance(profile.get("name"), str) else None,
        }


def _google_profile(code: str, redirect_uri: str, verifier: str, nonce_hash: str | None) -> dict:
    client_id = _required("HW_GOOGLE_CLIENT_ID")
    client_secret = _required("HW_GOOGLE_CLIENT_SECRET")
    with httpx.Client(timeout=15) as client:
        token_response = client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
        )
        token_response.raise_for_status()
        id_token = token_response.json().get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise ValueError("google_id_token_missing")
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError("google_signing_key_invalid")
        jwks_response = client.get("https://www.googleapis.com/oauth2/v3/certs")
        jwks_response.raise_for_status()
        jwks = jwks_response.json().get("keys", [])
        jwk = next(
            (item for item in jwks
             if isinstance(item, dict) and item.get("kid") == header["kid"]),
            None,
        )
        if jwk is None:
            raise ValueError("google_signing_key_not_found")
        signing_key = jwt.PyJWK.from_dict(jwk, algorithm="RS256").key
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            leeway=30,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        nonce = claims.get("nonce")
        if not nonce_hash or not isinstance(nonce, str) or digest(nonce) != nonce_hash:
            raise ValueError("google_nonce_invalid")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise ValueError("google_subject_missing")
        email = claims.get("email")
        email_verified = claims.get("email_verified") is True
        return {
            "issuer": "https://accounts.google.com",
            "subject": subject,
            "username": None,
            "email": email if email_verified and isinstance(email, str) else None,
            "display_name": claims.get("name") if isinstance(claims.get("name"), str) else None,
        }


@router.get("/{provider}/callback")
def oauth_callback(
    provider: str,
    request: Request,
    state: str,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if provider not in {"github", "google"}:
        raise HTTPException(status_code=404, detail="OAuth provider not found.")
    browser_state = request.cookies.get(_state_cookie_name(state), "")
    if not browser_state or not secrets.compare_digest(browser_state, state):
        return _oauth_finish(provider, state, "invalid_state")
    try:
        transaction = consume_oauth_request(db, state, provider=provider)
        db.commit()  # Consume state before contacting the provider; callbacks are single-use.
    except OAuthFlowError:
        db.rollback()
        return _oauth_finish(provider, state, "invalid_state")

    if error or not code:
        return _oauth_finish(provider, state, "cancelled")

    if transaction["intent"] == "link":
        current_session = request.cookies.get(SESSION_COOKIE, "")
        if (
            not current_session
            or digest(current_session) != transaction["session_token_hash"]
        ):
            return _oauth_finish(provider, state, "session_changed")
        authenticated = authenticate_session(db, current_session)
        db.commit()
        if authenticated is None or authenticated[1].id != transaction["user_id"]:
            return _oauth_finish(provider, state, "session_changed")

    try:
        profile = (
            _github_profile(code, transaction["redirect_uri"], transaction["code_verifier"])
            if provider == "github"
            else _google_profile(
                code,
                transaction["redirect_uri"],
                transaction["code_verifier"],
                transaction["nonce_hash"],
            )
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError):
        return _oauth_finish(provider, state, "provider_error")

    try:
        if transaction["intent"] == "link":
            user = db.scalar(select(User).where(
                User.id == transaction["user_id"]
            ).with_for_update())
            if user is None or user.status != "active":
                raise AccountServiceError("user_not_active")
            identity = link_external_identity(
                db,
                user_id=user.id,
                provider=provider,
                issuer=profile["issuer"],
                provider_subject=profile["subject"],
                provider_username=profile["username"],
                provider_email=profile["email"],
            )
        else:
            identity = db.scalar(select(ExternalIdentity).where(
                ExternalIdentity.issuer == profile["issuer"],
                ExternalIdentity.provider_subject == profile["subject"],
                ExternalIdentity.disabled_at.is_(None),
            ))
            if identity is None:
                db.rollback()
                return _oauth_finish(provider, state, "account_not_linked")
            user = db.scalar(select(User).where(
                User.id == identity.user_id
            ).with_for_update())
            if user is None or user.status != "active":
                db.rollback()
                return _oauth_finish(provider, state, "account_unavailable")
            identity.last_authenticated_at = utc_now()
            if profile["username"]:
                identity.provider_username = profile["username"]
            if profile["email"]:
                identity.provider_email = profile["email"]

        session, raw_session_token = create_session(
            db, user_id=user.id, user_agent=request.headers.get("user-agent")
        )
        db.commit()
    except AccountServiceError:
        db.rollback()
        return _oauth_finish(provider, state, "identity_unavailable")

    response = _oauth_finish(provider, state, "success")
    lifetime = int((session.expires_at - utc_now()).total_seconds())
    _set_session_cookies(response, raw_session_token, lifetime)
    return response

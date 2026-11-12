from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.account_services import create_session
from app.db import Base, get_db
from app.main import app
from app.models import ExternalIdentity, User
from app.oauth_services import (
    OAuthFlowError,
    consume_oauth_request,
    create_oauth_request,
)


@pytest.fixture
def oauth_factory(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setenv("HW_COOKIE_SECURE", "false")
    monkeypatch.setenv("HW_PUBLIC_BASE_URL", "https://catalog.example.com")
    monkeypatch.setenv("HW_FRONTEND_URL", "https://catalog.example.com")
    monkeypatch.setenv("HW_OAUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("HW_GITHUB_CLIENT_ID", "github-client-id")
    monkeypatch.setenv("HW_GITHUB_CLIENT_SECRET", "github-client-secret")
    monkeypatch.setenv(
        "HW_GITHUB_REDIRECT_URI",
        "https://api.example.com/api/v1/account/oauth/github/callback",
    )
    monkeypatch.setenv("HW_GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("HW_GOOGLE_CLIENT_SECRET", "google-client-secret")
    monkeypatch.setenv(
        "HW_GOOGLE_REDIRECT_URI",
        "https://api.example.com/api/v1/account/oauth/google/callback",
    )

    yield factory

    app.dependency_overrides.clear()
    engine.dispose()


def _state_from_redirect(response):
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def test_oauth_state_is_single_use_and_pkce_verifier_is_decrypted(oauth_factory):
    with oauth_factory() as db:
        _row, state, verifier, nonce = create_oauth_request(
            db,
            provider="google",
            redirect_uri="https://api.example.com/callback",
        )
        db.commit()

        transaction = consume_oauth_request(db, state, provider="google")
        db.commit()

        assert transaction["code_verifier"] == verifier
        assert transaction["nonce_hash"]
        assert nonce

        with pytest.raises(OAuthFlowError, match="invalid_oauth_state"):
            consume_oauth_request(db, state, provider="google")


def test_oauth_login_redirect_contains_state_and_s256_pkce(oauth_factory):
    response = TestClient(app).get(
        "/api/v1/account/oauth/github/start",
        follow_redirects=False,
    )
    assert response.status_code == 303
    parsed = urlparse(response.headers["location"])
    params = parse_qs(parsed.query)
    assert parsed.netloc == "github.com"
    assert params["state"][0]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"][0]


def test_github_oauth_callback_logs_in_only_linked_identity(
    oauth_factory, monkeypatch
):
    with oauth_factory() as db:
        user = User(status="active", display_name="Collector")
        db.add(user)
        db.flush()
        db.add(ExternalIdentity(
            user_id=user.id,
            provider="github",
            issuer="https://github.com",
            provider_subject="12345",
            provider_username="collector",
        ))
        db.commit()

    monkeypatch.setattr(
        "app.oauth_api._github_profile",
        lambda *_args: {
            "issuer": "https://github.com",
            "subject": "12345",
            "username": "collector",
            "email": None,
            "display_name": "Collector",
        },
    )
    client = TestClient(app)
    start = client.get(
        "/api/v1/account/oauth/github/start",
        follow_redirects=False,
    )
    state = _state_from_redirect(start)
    callback = client.get(
        "/api/v1/account/oauth/github/callback",
        params={"state": state, "code": "mock-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert "oauth=success" in callback.headers["location"]
    assert "hw_session" in callback.cookies
    assert "hw_csrf" in callback.cookies

    replay = client.get(
        "/api/v1/account/oauth/github/callback",
        params={"state": state, "code": "mock-code"},
        follow_redirects=False,
    )
    assert "oauth=invalid_state" in replay.headers["location"]


def test_oauth_login_does_not_auto_link_by_matching_email(
    oauth_factory, monkeypatch
):
    with oauth_factory() as db:
        user = User(status="active", display_name="Existing account")
        db.add(user)
        db.commit()

    monkeypatch.setattr(
        "app.oauth_api._github_profile",
        lambda *_args: {
            "issuer": "https://github.com",
            "subject": "unlinked-678",
            "username": "new-provider-user",
            "email": "same@example.com",
            "display_name": "Provider name",
        },
    )
    client = TestClient(app)
    start = client.get(
        "/api/v1/account/oauth/github/start",
        follow_redirects=False,
    )
    state = _state_from_redirect(start)
    callback = client.get(
        "/api/v1/account/oauth/github/callback",
        params={"state": state, "code": "mock-code"},
        follow_redirects=False,
    )
    assert "oauth=account_not_linked" in callback.headers["location"]
    with oauth_factory() as db:
        assert db.scalar(select(ExternalIdentity)) is None


def test_oauth_link_requires_csrf_and_binds_to_current_session(
    oauth_factory, monkeypatch
):
    with oauth_factory() as db:
        user = User(status="active", display_name="Collector")
        db.add(user)
        db.flush()
        session, raw_token = create_session(db, user_id=user.id)
        user_id = user.id
        db.commit()

    client = TestClient(app)
    client.cookies.set("hw_session", raw_token)
    client.cookies.set("hw_csrf", "csrf-value")
    denied = client.post(
        "/api/v1/account/oauth/github/link",
        headers={"Origin": "https://catalog.example.com"},
        follow_redirects=False,
    )
    assert denied.status_code == 403

    json_started = client.post(
        "/api/v1/account/oauth/github/link",
        params={"response_mode": "json"},
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-value",
        },
        follow_redirects=False,
    )
    assert json_started.status_code == 200
    assert json_started.json()["authorization_url"].startswith(
        "https://github.com/login/oauth/authorize?"
    )
    assert "hw_oauth_state_" in json_started.headers.get("set-cookie", "")

    started = client.post(
        "/api/v1/account/oauth/github/link",
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-value",
        },
        follow_redirects=False,
    )
    assert started.status_code == 303
    state = _state_from_redirect(started)

    # A different browser session cannot complete an account-link transaction.
    client.cookies.set("hw_session", "different-session-token")
    callback = client.get(
        "/api/v1/account/oauth/github/callback",
        params={"state": state, "code": "mock-code"},
        follow_redirects=False,
    )
    assert "oauth=session_changed" in callback.headers["location"]
    with oauth_factory() as db:
        assert db.scalar(select(ExternalIdentity).where(
            ExternalIdentity.user_id == user_id
        )) is None

from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.account_services import create_session
from app.db import Base, get_db
from app.main import app
from app.models import (
    AuthRateLimitBucket,
    EmailAddress,
    OutboundEmail,
    PasswordCredential,
    PasswordResetToken,
    User,
    UserSession,
)


@pytest.fixture
def password_api(monkeypatch):
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
    monkeypatch.setenv("HW_AUTH_RATE_LIMIT_KEY", "test-rate-limit-secret-" + "x" * 32)
    monkeypatch.setenv("HW_EMAIL_ENCRYPTION_KEY", Fernet.generate_key().decode())

    with factory() as db:
        user = User(status="active", display_name="Collector")
        db.add(user)
        db.flush()
        email = EmailAddress(
            user_id=user.id,
            email_normalized="collector@example.com",
            email_display="collector@example.com",
            is_primary=True,
            verified_at=__import__("app.models", fromlist=["utc_now"]).utc_now(),
        )
        db.add(email)
        db.flush()
        user_id = user.id
        db.commit()

    yield factory, user_id
    app.dependency_overrides.clear()
    engine.dispose()


def _client():
    return TestClient(app)


def _set_password_session(factory, user_id):
    with factory() as db:
        session, raw = create_session(db, user_id=user_id)
        db.commit()
    client = _client()
    client.cookies.set("hw_session", raw)
    client.cookies.set("hw_csrf", "csrf-token")
    return client, raw


def test_set_password_then_login(password_api):
    factory, user_id = password_api
    client, _raw = _set_password_session(factory, user_id)
    response = client.post(
        "/api/v1/account/password/set",
        json={"password": "correct horse battery staple"},
        headers={"Origin": "https://catalog.example.com", "X-CSRF-Token": "csrf-token"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "password_configured"

    login = _client().post(
        "/api/v1/account/password/login",
        json={"email": "COLLECTOR@example.com", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["id"] == user_id
    assert "hw_session" in login.cookies

    with factory() as db:
        credential = db.scalar(select(PasswordCredential).where(
            PasswordCredential.user_id == user_id
        ))
        assert credential.password_hash.startswith("$argon2id$")
        assert credential.password_hash != "correct horse battery staple"


def test_password_login_has_generic_failure_and_persistent_throttle(password_api):
    factory, _user_id = password_api
    client = _client()
    for _ in range(5):
        response = client.post(
            "/api/v1/account/password/login",
            json={"email": "missing@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password."

    blocked = client.post(
        "/api/v1/account/password/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )
    assert blocked.status_code == 429
    with factory() as db:
        assert db.scalar(select(AuthRateLimitBucket)) is not None


def test_password_reset_is_single_use_and_revokes_existing_sessions(password_api):
    factory, user_id = password_api
    client, old_raw = _set_password_session(factory, user_id)
    set_response = client.post(
        "/api/v1/account/password/set",
        json={"password": "initial password phrase"},
        headers={"Origin": "https://catalog.example.com", "X-CSRF-Token": "csrf-token"},
    )
    assert set_response.status_code == 200

    request_response = _client().post(
        "/api/v1/account/password/reset/request",
        json={"email": "collector@example.com"},
    )
    assert request_response.status_code == 202
    assert request_response.json()["status"] == "if_account_is_eligible_email_will_be_sent"

    with factory() as db:
        queued = db.scalar(select(OutboundEmail).where(OutboundEmail.status == "pending"))
        payload = Fernet(__import__("os").environ["HW_EMAIL_ENCRYPTION_KEY"].encode()).decrypt(
            queued.encrypted_payload.encode()
        ).decode()
        link = __import__("re").search(r"https://catalog\\.example\\.com/account/reset-password\\?token=([^\\s]+)", payload)
        assert link
        token = link.group(1)

    reset = _client().post(
        "/api/v1/account/password/reset/confirm",
        json={"token": token, "password": "a completely new password"},
    )
    assert reset.status_code == 200
    replay = _client().post(
        "/api/v1/account/password/reset/confirm",
        json={"token": token, "password": "another new password"},
    )
    assert replay.status_code == 400

    with factory() as db:
        old_session = db.scalar(select(UserSession).where(UserSession.token_hash == __import__("hashlib").sha256(old_raw.encode()).hexdigest()))
        assert old_session.revoked_at is not None
        reset_token = db.scalar(select(PasswordResetToken))
        assert reset_token.consumed_at is not None

    login = _client().post(
        "/api/v1/account/password/login",
        json={"email": "collector@example.com", "password": "a completely new password"},
    )
    assert login.status_code == 200


def test_unverified_email_cannot_use_password_login(password_api):
    factory, user_id = password_api
    client, _raw = _set_password_session(factory, user_id)
    assert client.post(
        "/api/v1/account/password/set",
        json={"password": "correct horse battery staple"},
        headers={"Origin": "https://catalog.example.com", "X-CSRF-Token": "csrf-token"},
    ).status_code == 200
    with factory() as db:
        email = db.scalar(select(EmailAddress).where(EmailAddress.user_id == user_id))
        email.verified_at = None
        db.commit()

    response = _client().post(
        "/api/v1/account/password/login",
        json={"email": "collector@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

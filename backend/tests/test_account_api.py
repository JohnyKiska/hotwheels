from cryptography.fernet import Fernet
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, get_db
from app.main import app
from app.account_services import create_invitation, create_session
from app.models import (
    EmailAddress,
    OutboundEmail,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)


@pytest.fixture
def api_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

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
    monkeypatch.setenv("HW_ALLOWED_ORIGINS", "https://catalog.example.com")
    monkeypatch.setenv("HW_EMAIL_ENCRYPTION_KEY", Fernet.generate_key().decode())

    yield factory

    app.dependency_overrides.clear()
    engine.dispose()


def create_authenticated_client(factory, *, role_code="admin", permissions=("users.manage", "roles.assign")):
    with factory() as db:
        user = User(status="active", display_name="Admin")
        role = Role(code=role_code, name=role_code.title())
        db.add_all([user, role])
        db.flush()
        for code in permissions:
            permission = db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, description=code)
                db.add(permission)
                db.flush()
            db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        db.add(UserRole(user_id=user.id, role_id=role.id))
        session, raw_token = create_session(db, user_id=user.id)
        user_id = user.id
        db.commit()

    client = TestClient(app)
    client.cookies.set("hw_session", raw_token)
    client.cookies.set("hw_csrf", "csrf-test-token")
    return client, user_id


def test_account_me_requires_valid_session_and_returns_role_ids(api_factory):
    client, user_id = create_authenticated_client(api_factory, permissions=("users.manage",))
    response = client.get("/api/v1/account/me")

    assert response.status_code == 200
    assert response.json()["id"] == user_id
    assert response.json()["status"] == "active"
    assert len(response.json()["role_ids"]) == 1


def test_invitation_api_requires_csrf_and_queues_encrypted_email(api_factory):
    client, user_id = create_authenticated_client(api_factory)

    payload = {"email": "collector@example.com", "recipient_name": "Collector"}
    denied = client.post(
        "/api/v1/account/invitations",
        json=payload,
        headers={"Origin": "https://catalog.example.com"},
    )
    assert denied.status_code == 403

    response = client.post(
        "/api/v1/account/invitations",
        json=payload,
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-test-token",
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "collector@example.com"

    with api_factory() as db:
        queued = db.scalar(select(OutboundEmail))
        assert queued is not None
        assert queued.recipient_email == "collector@example.com"
        assert queued.status == "pending"


def test_invitation_acceptance_creates_session_cookie_and_me(api_factory):
    with api_factory() as db:
        inviter = User(status="active", display_name="Admin")
        db.add(inviter)
        db.flush()
        invitation, raw_token = create_invitation(
            db, email="new-user@example.com", invited_by_user_id=inviter.id
        )
        db.commit()

    client = TestClient(app)
    response = client.post(
        "/api/v1/account/invitations/accept",
        json={"token": raw_token, "display_name": "New User"},
    )
    assert response.status_code == 201
    assert response.json()["email_verified"] is True
    assert "hw_session" in response.cookies
    assert "hw_csrf" in response.cookies

    client.cookies.update(response.cookies)
    me = client.get("/api/v1/account/me")
    assert me.status_code == 200
    assert me.json()["display_name"] == "New User"


def test_logout_revokes_session_and_clears_cookies(api_factory):
    client, _user_id = create_authenticated_client(api_factory, permissions=("users.manage",))

    denied = client.post(
        "/api/v1/account/logout",
        headers={"Origin": "https://catalog.example.com"},
    )
    assert denied.status_code == 403

    response = client.post(
        "/api/v1/account/logout",
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-test-token",
        },
    )
    assert response.status_code == 204
    assert "hw_session" not in response.cookies


def test_invitation_api_denies_user_without_users_manage_permission(api_factory):
    client, _user_id = create_authenticated_client(
        api_factory, role_code="viewer", permissions=()
    )
    response = client.post(
        "/api/v1/account/invitations",
        json={"email": "blocked@example.com"},
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-test-token",
        },
    )
    assert response.status_code == 403

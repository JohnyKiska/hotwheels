import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.account_services import create_session
from app.db import Base, get_db
from app.main import app
from app.models import (
    AuditEvent, Permission, Role, RolePermission, User, UserRole, UserSession,
)


@pytest.fixture
def api_factory(monkeypatch):
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
    monkeypatch.setenv("HW_ALLOWED_ORIGINS", "https://catalog.example.com")
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def authenticated_client(factory, permissions=("users.read", "users.manage", "roles.assign"), *, super_admin=False):
    with factory() as db:
        actor = User(status="active", display_name="Admin")
        actor_role = Role(code=f"test_actor_{uuid.uuid4().hex[:10]}", name="Test actor")
        db.add_all([actor, actor_role])
        db.flush()
        for code in permissions:
            permission = db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, description=code)
                db.add(permission)
                db.flush()
            db.add(RolePermission(role_id=actor_role.id, permission_id=permission.id))
        db.add(UserRole(user_id=actor.id, role_id=actor_role.id))
        if super_admin:
            root = db.scalar(select(Role).where(Role.code == "super_admin"))
            if root is None:
                root = Role(code="super_admin", name="Super Admin")
                db.add(root)
                db.flush()
            db.add(UserRole(user_id=actor.id, role_id=root.id))
        _session, raw_token = create_session(db, user_id=actor.id)
        actor_id = actor.id
        db.commit()

    client = TestClient(app)
    client.cookies.set("hw_session", raw_token)
    client.cookies.set("hw_csrf", "csrf-test-token")
    return client, actor_id


def csrf_headers():
    return {
        "Origin": "https://catalog.example.com",
        "X-CSRF-Token": "csrf-test-token",
    }


def test_user_list_requires_users_read_and_supports_search(api_factory):
    with api_factory() as db:
        user = User(status="active", display_name="Collector One")
        db.add(user)
        db.flush()
        from app.models import EmailAddress
        db.add(EmailAddress(
            user_id=user.id,
            email_normalized="collector@example.com",
            email_display="Collector@example.com",
            is_primary=True,
        ))
        db.commit()

    client, _ = authenticated_client(api_factory, permissions=("users.read",))
    response = client.get("/api/v1/admin/users?q=collector@example.com")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["display_name"] == "Collector One"

    denied, _ = authenticated_client(api_factory, permissions=())
    assert denied.get("/api/v1/admin/users").status_code == 403


def test_role_assignment_requires_csrf_and_audits_reason(api_factory):
    with api_factory() as db:
        target = User(status="active", display_name="Collector")
        role = Role(code="editor", name="Editor")
        db.add_all([target, role])
        db.commit()
        target_id, role_id = target.id, role.id

    client, actor_id = authenticated_client(api_factory)
    payload = {"role_id": role_id, "reason": "Approved contributor access"}
    denied = client.post(f"/api/v1/admin/users/{target_id}/roles", json=payload)
    assert denied.status_code == 403

    response = client.post(
        f"/api/v1/admin/users/{target_id}/roles",
        json=payload,
        headers=csrf_headers(),
    )
    assert response.status_code == 201
    assert response.json()["role"] == "editor"

    with api_factory() as db:
        assignment = db.scalar(select(UserRole).where(
            UserRole.user_id == target_id,
            UserRole.role_id == role_id,
            UserRole.revoked_at.is_(None),
        ))
        assert assignment is not None
        event = db.scalar(select(AuditEvent).where(
            AuditEvent.action == "user.role.assigned",
            AuditEvent.target_id == target_id,
        ))
        assert event.actor_user_id == actor_id
        assert event.event_metadata["reason"] == payload["reason"]


def test_regular_admin_cannot_assign_or_revoke_admin_or_super_admin(api_factory):
    with api_factory() as db:
        target = User(status="active", display_name="Target")
        admin = Role(code="admin", name="Administrator")
        root = Role(code="super_admin", name="Super Admin")
        db.add_all([target, admin, root])
        db.flush()
        db.add(UserRole(user_id=target.id, role_id=admin.id))
        target_id, admin_id, root_id = target.id, admin.id, root.id
        db.commit()

    client, _ = authenticated_client(api_factory)
    denied_admin = client.post(
        f"/api/v1/admin/users/{target_id}/roles",
        json={"role_id": admin_id, "reason": "Promote"},
        headers=csrf_headers(),
    )
    assert denied_admin.status_code == 403

    denied_root = client.post(
        f"/api/v1/admin/users/{target_id}/roles",
        json={"role_id": root_id, "reason": "Promote"},
        headers=csrf_headers(),
    )
    assert denied_root.status_code == 403

    denied_revoke = client.post(
        f"/api/v1/admin/users/{target_id}/roles/{admin_id}/revoke",
        json={"reason": "Demote"},
        headers=csrf_headers(),
    )
    assert denied_revoke.status_code == 403


def test_super_admin_can_assign_admin_but_not_super_admin(api_factory):
    with api_factory() as db:
        target = User(status="active", display_name="New admin")
        admin = Role(code="admin", name="Administrator")
        root = Role(code="super_admin", name="Super Admin")
        db.add_all([target, admin, root])
        db.commit()
        target_id, admin_id, root_id = target.id, admin.id, root.id

    client, _ = authenticated_client(api_factory, super_admin=True)
    assigned = client.post(
        f"/api/v1/admin/users/{target_id}/roles",
        json={"role_id": admin_id, "reason": "Trusted administrator"},
        headers=csrf_headers(),
    )
    assert assigned.status_code == 201
    blocked = client.post(
        f"/api/v1/admin/users/{target_id}/roles",
        json={"role_id": root_id, "reason": "Not permitted"},
        headers=csrf_headers(),
    )
    assert blocked.status_code == 403


def test_suspend_user_revokes_sessions_and_prevents_self_suspend(api_factory):
    with api_factory() as db:
        target = User(status="active", display_name="Collector")
        db.add(target)
        db.flush()
        _session, target_token = create_session(db, user_id=target.id)
        target_id = target.id
        db.commit()

    client, _ = authenticated_client(api_factory)
    response = client.patch(
        f"/api/v1/admin/users/{target_id}/status",
        json={"status": "suspended", "reason": "Account security review"},
        headers=csrf_headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"

    with api_factory() as db:
        session = db.scalar(select(UserSession).where(UserSession.user_id == target_id))
        assert session.revoked_at is not None
        assert session.revoke_reason == "account_suspended"
        event = db.scalar(select(AuditEvent).where(
            AuditEvent.action == "admin.user.suspended",
            AuditEvent.target_id == target_id,
        ))
        assert event.event_metadata["reason"] == "Account security review"

    self_client, self_id = authenticated_client(api_factory)
    self_denied = self_client.patch(
        f"/api/v1/admin/users/{self_id}/status",
        json={"status": "suspended", "reason": "Self suspend"},
        headers=csrf_headers(),
    )
    assert self_denied.status_code == 409


def test_super_admin_cannot_be_suspended_or_managed(api_factory):
    with api_factory() as db:
        root = User(status="active", display_name="Root")
        root_role = Role(code="super_admin", name="Super Admin")
        db.add_all([root, root_role])
        db.flush()
        db.add(UserRole(user_id=root.id, role_id=root_role.id))
        root_id = root.id
        db.commit()

    client, _ = authenticated_client(api_factory)
    response = client.patch(
        f"/api/v1/admin/users/{root_id}/status",
        json={"status": "suspended", "reason": "Try"},
        headers=csrf_headers(),
    )
    assert response.status_code == 403

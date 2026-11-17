import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.account_services import create_session
from app.db import Base, get_db
from app.main import app
from app.models import Casting, ChangeLog, Permission, Role, RolePermission, User, UserRole


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


def authenticated_client(factory, permissions=("catalog.read", "catalog.update")):
    with factory() as db:
        user = User(status="active", display_name="Catalog admin")
        role = Role(code=f"test_admin_{uuid.uuid4().hex[:12]}", name="Test admin")
        db.add_all([user, role])
        db.flush()
        for code in permissions:
            permission = Permission(code=code, description=code)
            db.add(permission)
            db.flush()
            db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        db.add(UserRole(user_id=user.id, role_id=role.id))
        _session, raw_token = create_session(db, user_id=user.id)
        user_id = user.id
        db.commit()

    client = TestClient(app)
    client.cookies.set("hw_session", raw_token)
    client.cookies.set("hw_csrf", "csrf-test-token")
    return client, user_id


def test_casting_list_requires_read_permission_and_paginates(api_factory):
    with api_factory() as db:
        db.add_all([
            Casting(name="Custom Camaro", status="confirmed"),
            Casting(name="BMW 323", status="candidate"),
        ])
        db.commit()

    client, _ = authenticated_client(api_factory)
    response = client.get("/api/v1/admin/catalog/castings?q=camaro")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["name"] == "Custom Camaro"

    viewer, _ = authenticated_client(api_factory, permissions=())
    denied = viewer.get("/api/v1/admin/catalog/castings")
    assert denied.status_code == 403


def test_casting_patch_requires_csrf_and_writes_audit_log(api_factory):
    with api_factory() as db:
        casting = Casting(name="Custom Camaro", status="candidate")
        db.add(casting)
        db.commit()
        casting_id = casting.id

    client, user_id = authenticated_client(api_factory)
    payload = {"name": "Custom Camaro (updated)", "reason": "Verified against primary source"}

    denied = client.patch(
        f"/api/v1/admin/catalog/castings/{casting_id}",
        json=payload,
        headers={"Origin": "https://catalog.example.com"},
    )
    assert denied.status_code == 403

    response = client.patch(
        f"/api/v1/admin/catalog/castings/{casting_id}",
        json=payload,
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-test-token",
        },
    )
    assert response.status_code == 200
    assert response.json()["name"] == payload["name"]

    with api_factory() as db:
        event = db.scalar(select(ChangeLog).where(ChangeLog.entity_id == casting_id))
        assert event is not None
        assert event.entity_type == "casting"
        assert event.action == "update"
        assert event.actor_type == "user"
        assert event.actor_id == user_id
        assert event.reason == payload["reason"]
        assert event.old_values == {"name": "Custom Camaro"}
        assert event.new_values == {"name": payload["name"]}


def test_casting_patch_rejects_empty_reason_and_unknown_fields(api_factory):
    with api_factory() as db:
        casting = Casting(name="Custom Camaro")
        db.add(casting)
        db.commit()
        casting_id = casting.id

    client, _ = authenticated_client(api_factory)
    headers = {
        "Origin": "https://catalog.example.com",
        "X-CSRF-Token": "csrf-test-token",
    }
    empty_reason = client.patch(
        f"/api/v1/admin/catalog/castings/{casting_id}",
        json={"name": "Renamed", "reason": "   "},
        headers=headers,
    )
    assert empty_reason.status_code == 422

    unknown_field = client.patch(
        f"/api/v1/admin/catalog/castings/{casting_id}",
        json={"name": "Renamed", "reason": "Reviewed", "actor_id": "spoofed"},
        headers=headers,
    )
    assert unknown_field.status_code == 422

    with api_factory() as db:
        assert db.scalar(select(ChangeLog).where(ChangeLog.entity_id == casting_id)) is None

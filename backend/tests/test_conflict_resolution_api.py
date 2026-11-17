import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.account_services import create_session
from app.db import Base, get_db
from app.main import app
from app.models import ChangeLog, Conflict, Permission, Role, RolePermission, User, UserRole


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
        actor = User(status="active", display_name="Moderator")
        role = Role(code=f"test_moderator_{uuid.uuid4().hex[:10]}", name="Test moderator")
        db.add_all([actor, role])
        db.flush()
        for code in permissions:
            permission = db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, description=code)
                db.add(permission)
                db.flush()
            db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        db.add(UserRole(user_id=actor.id, role_id=role.id))
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


def create_conflict(factory):
    with factory() as db:
        conflict = Conflict(
            conflict_type="evidence_disagreement",
            status="open",
            severity="medium",
            attribute_name="wheel_type",
        )
        db.add(conflict)
        db.commit()
        return conflict.id


def test_moderation_reads_require_catalog_read(api_factory):
    conflict_id = create_conflict(api_factory)
    anonymous = TestClient(app)
    assert anonymous.get("/api/v1/admin/moderation/conflicts").status_code == 401

    denied, _ = authenticated_client(api_factory, permissions=())
    assert denied.get("/api/v1/admin/moderation/conflicts").status_code == 403

    client, _ = authenticated_client(api_factory, permissions=("catalog.read",))
    response = client.get("/api/v1/admin/moderation/conflicts")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    detail = client.get(f"/api/v1/admin/moderation/conflicts/{conflict_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == conflict_id


def test_resolution_requires_update_permission_and_csrf(api_factory):
    conflict_id = create_conflict(api_factory)
    reader, _ = authenticated_client(api_factory, permissions=("catalog.read",))
    payload = {
        "status": "resolved",
        "resolution": "Keep the supported value",
        "reason": "Compared the source observations",
    }
    assert reader.post(
        f"/api/v1/admin/moderation/conflicts/{conflict_id}/resolve",
        json=payload,
        headers=csrf_headers(),
    ).status_code == 403

    editor, _ = authenticated_client(api_factory, permissions=("catalog.update",))
    denied_csrf = editor.post(
        f"/api/v1/admin/moderation/conflicts/{conflict_id}/resolve",
        json=payload,
    )
    assert denied_csrf.status_code == 403


def test_resolution_uses_authenticated_actor_and_rejects_spoofed_actor_fields(api_factory):
    conflict_id = create_conflict(api_factory)
    client, actor_id = authenticated_client(api_factory)
    url = f"/api/v1/admin/moderation/conflicts/{conflict_id}/resolve"
    payload = {
        "status": "resolved",
        "resolution": "Keep the supported value",
        "reason": "Compared the source observations",
        "actor_type": "system",
        "actor_id": "forged-user-id",
    }
    rejected = client.post(url, json=payload, headers=csrf_headers())
    assert rejected.status_code == 422

    payload.pop("actor_type")
    payload.pop("actor_id")
    response = client.post(url, json=payload, headers=csrf_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"

    with api_factory() as db:
        audit = db.scalar(select(ChangeLog).where(
            ChangeLog.entity_type == "conflict",
            ChangeLog.entity_id == conflict_id,
            ChangeLog.action == "resolve_conflict",
        ))
        assert audit is not None
        assert audit.actor_type == "human"
        assert audit.actor_id == actor_id
        assert audit.reason == payload["reason"]


def test_revision_requires_csrf_and_records_authenticated_actor(api_factory):
    conflict_id = create_conflict(api_factory)
    client, actor_id = authenticated_client(api_factory)
    url = f"/api/v1/admin/moderation/conflicts/{conflict_id}/resolve"
    first = client.post(url, json={
        "status": "resolved",
        "resolution": "Initial decision",
        "reason": "Initial evidence review",
    }, headers=csrf_headers())
    assert first.status_code == 200

    revise_url = f"/api/v1/admin/moderation/conflicts/{conflict_id}/revise-resolution"
    revised = client.post(revise_url, json={
        "status": "accepted_difference",
        "resolution": "Treat as a legitimate regional difference",
        "reason": "New primary-source evidence",
    }, headers=csrf_headers())
    assert revised.status_code == 200
    assert revised.json()["status"] == "accepted_difference"

    with api_factory() as db:
        events = db.scalars(select(ChangeLog).where(
            ChangeLog.entity_type == "conflict",
            ChangeLog.entity_id == conflict_id,
        ).order_by(ChangeLog.created_at, ChangeLog.id)).all()
        assert [event.action for event in events] == [
            "resolve_conflict", "revise_conflict_resolution"
        ]
        assert all(event.actor_id == actor_id for event in events)
        assert all(event.actor_type == "human" for event in events)


def test_resolution_validates_reason_and_unknown_conflict(api_factory):
    client, _ = authenticated_client(api_factory)
    url = "/api/v1/admin/moderation/conflicts/missing/resolve"
    payload = {
        "status": "resolved",
        "resolution": "No decision",
        "reason": "Test missing conflict",
    }
    missing = client.post(url, json=payload, headers=csrf_headers())
    assert missing.status_code == 404

    conflict_id = create_conflict(api_factory)
    payload["reason"] = "   "
    blank = client.post(
        f"/api/v1/admin/moderation/conflicts/{conflict_id}/resolve",
        json=payload,
        headers=csrf_headers(),
    )
    assert blank.status_code == 422
    with api_factory() as db:
        conflict = db.get(Conflict, conflict_id)
        assert conflict.status == "open"
        assert db.query(ChangeLog).count() == 0

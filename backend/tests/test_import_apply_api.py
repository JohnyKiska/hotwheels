import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.account_services import create_session
from app.db import Base, get_db
from app.main import app
from app.models import (
    ChangeLog,
    Evidence,
    Permission,
    Role,
    RolePermission,
    SourceRecord,
    User,
    UserRole,
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
    monkeypatch.setenv("HW_ALLOWED_ORIGINS", "https://catalog.example.com")

    yield factory

    app.dependency_overrides.clear()
    engine.dispose()


def _observation():
    return {
        "source": {
            "code": "mainline_checklist",
            "record_type": "mainline_checklist_row",
            "format": "tsv",
            "record_url": "https://example.test/mainline.tsv",
            "external_id": None,
        },
        "subject_hints": {"name": "'87 Dodge D100", "catalog_year": 2024},
        "claims": [
            {"attribute": "model_name", "value": "'87 Dodge D100", "raw_value": "'87 Dodge D100", "source_field": "Model"},
            {"attribute": "catalog_year", "value": 2024, "raw_value": "2024", "source_field": "Year"},
        ],
        "identifier_hints": [{"type_code": "toy_number", "raw_value": "038"}],
        "raw": {"source_row": 7, "source_values": {"Model": "'87 Dodge D100"}},
        "review_status": "candidate",
    }


def _client(factory, *, permissions=("catalog.create",)):
    with factory() as db:
        user = User(status="active", display_name="Import reviewer")
        role = Role(code="import-reviewer", name="Import reviewer")
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
        _session, raw_token = create_session(db, user_id=user.id)
        db.commit()

    client = TestClient(app)
    client.cookies.set("hw_session", raw_token)
    client.cookies.set("hw_csrf", "csrf-test-token")
    return client


def _headers(*, csrf=True):
    headers = {"Origin": "https://catalog.example.com"}
    if csrf:
        headers["X-CSRF-Token"] = "csrf-test-token"
    return headers


def _counts(factory):
    with factory() as db:
        return {
            "records": db.scalar(select(func.count()).select_from(SourceRecord)),
            "evidence": db.scalar(select(func.count()).select_from(Evidence)),
            "change_logs": db.scalar(select(func.count()).select_from(ChangeLog)),
        }


def test_apply_api_rejects_unauthenticated_request_without_writes(api_factory):
    response = TestClient(app).post(
        "/api/v1/imports/apply",
        json={"observation": _observation()},
        headers=_headers(),
    )

    assert response.status_code == 401
    assert _counts(api_factory) == {"records": 0, "evidence": 0, "change_logs": 0}


def test_apply_api_requires_csrf(api_factory):
    client = _client(api_factory)
    response = client.post(
        "/api/v1/imports/apply",
        json={"observation": _observation()},
        headers=_headers(csrf=False),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF validation failed."
    assert _counts(api_factory) == {"records": 0, "evidence": 0, "change_logs": 0}


def test_apply_api_requires_catalog_create_permission(api_factory):
    client = _client(api_factory, permissions=())
    response = client.post(
        "/api/v1/imports/apply",
        json={"observation": _observation()},
        headers=_headers(),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permission."
    assert _counts(api_factory) == {"records": 0, "evidence": 0, "change_logs": 0}


def test_apply_api_persists_evidence_only_and_replay_is_idempotent(api_factory):
    client = _client(api_factory)
    payload = {"observation": _observation(), "reason": "Reviewed source snapshot"}

    first = client.post("/api/v1/imports/apply", json=payload, headers=_headers())
    replay = client.post("/api/v1/imports/apply", json=payload, headers=_headers())

    assert first.status_code == 201
    assert first.json()["status"] == "applied"
    assert first.json()["mode"] == "evidence_only"
    assert first.json()["writes_to_catalog_entities"] is False
    assert first.json()["record_created"] is True
    assert first.json()["evidence_created"] == 2

    assert replay.status_code == 201
    assert replay.json()["record_created"] is False
    assert replay.json()["evidence_created"] == 0
    assert replay.json()["source_record_id"] == first.json()["source_record_id"]
    assert _counts(api_factory) == {"records": 1, "evidence": 2, "change_logs": 1}

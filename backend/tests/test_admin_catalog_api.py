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
            permission = db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
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



def test_release_list_and_detail_are_permission_protected_and_include_links(api_factory):
    from app.models import CastingVariant, Release, Series, ReleaseSeries

    with api_factory() as db:
        casting = Casting(name="Custom Camaro", status="confirmed")
        db.add(casting)
        db.flush()
        variant = CastingVariant(
            casting_id=casting.id, name="Opening Hood", status="confirmed"
        )
        series = Series(name="Then and Now", status="confirmed")
        db.add_all([variant, series])
        db.flush()
        release = Release(
            casting_id=casting.id,
            casting_variant_id=variant.id,
            catalog_year=2025,
            name="Custom Camaro",
            assortment_number="123/250",
            status="confirmed",
        )
        db.add(release)
        db.flush()
        db.add(ReleaseSeries(release_id=release.id, series_id=series.id))
        release_id = release.id
        db.commit()

    client, _ = authenticated_client(api_factory)
    listed = client.get(
        "/api/v1/admin/catalog/releases?q=camaro&catalog_year=2025"
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    item = listed.json()["items"][0]
    assert item["casting_name"] == "Custom Camaro"
    assert item["casting_variant_name"] == "Opening Hood"
    assert item["series"] == [{"id": series.id, "name": "Then and Now"}]

    detail = client.get(f"/api/v1/admin/catalog/releases/{release_id}")
    assert detail.status_code == 200
    assert detail.json()["assortment_number"] == "123/250"

    denied, _ = authenticated_client(api_factory, permissions=())
    assert denied.get("/api/v1/admin/catalog/releases").status_code == 403


def test_release_patch_audits_changes_and_rejects_cross_casting_variant(api_factory):
    from app.models import CastingVariant, Release

    with api_factory() as db:
        first = Casting(name="Custom Camaro")
        second = Casting(name="BMW 323")
        db.add_all([first, second])
        db.flush()
        valid_variant = CastingVariant(casting_id=first.id, name="Opening Hood")
        foreign_variant = CastingVariant(casting_id=second.id, name="Different base")
        db.add_all([valid_variant, foreign_variant])
        db.flush()
        release = Release(
            casting_id=first.id, casting_variant_id=valid_variant.id,
            catalog_year=2025, name="Custom Camaro", assortment_number="123/250",
        )
        db.add(release)
        db.commit()
        release_id = release.id
        foreign_variant_id = foreign_variant.id

    client, user_id = authenticated_client(api_factory)
    headers = {
        "Origin": "https://catalog.example.com",
        "X-CSRF-Token": "csrf-test-token",
    }
    invalid = client.patch(
        f"/api/v1/admin/catalog/releases/{release_id}",
        json={"casting_variant_id": foreign_variant_id, "reason": "Wrong casting"},
        headers=headers,
    )
    assert invalid.status_code == 422

    updated = client.patch(
        f"/api/v1/admin/catalog/releases/{release_id}",
        json={"catalog_year": 2026, "name": "Custom Camaro (2026)", "reason": "Verified catalog"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["catalog_year"] == 2026

    with api_factory() as db:
        event = db.scalar(select(ChangeLog).where(ChangeLog.entity_id == release_id))
        assert event is not None
        assert event.entity_type == "release"
        assert event.actor_id == user_id
        assert event.old_values == {"catalog_year": 2025, "name": "Custom Camaro"}
        assert event.new_values == {"catalog_year": 2026, "name": "Custom Camaro (2026)"}


def test_casting_variant_patch_is_permissioned_and_audited(api_factory):
    from app.models import CastingVariant

    with api_factory() as db:
        casting = Casting(name="Custom Camaro")
        db.add(casting)
        db.flush()
        variant = CastingVariant(casting_id=casting.id, name="Opening Hood")
        db.add(variant)
        db.commit()
        variant_id = variant.id

    client, user_id = authenticated_client(api_factory)
    response = client.patch(
        f"/api/v1/admin/catalog/variants/{variant_id}",
        json={"status": "confirmed", "reason": "Physical comparison completed"},
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-test-token",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"

    with api_factory() as db:
        event = db.scalar(select(ChangeLog).where(ChangeLog.entity_id == variant_id))
        assert event is not None
        assert event.entity_type == "casting_variant"
        assert event.actor_id == user_id
        assert event.old_values == {"status": "candidate"}
        assert event.new_values == {"status": "confirmed"}



def test_casting_create_requires_create_permission_csrf_and_audits(api_factory):
    client, user_id = authenticated_client(
        api_factory, permissions=("catalog.read", "catalog.create")
    )
    payload = {
        "name": "  Custom Camaro  ",
        "description": "  First verified description  ",
        "first_known_year": 1968,
        "reason": "Verified against the reference catalog",
    }
    denied_csrf = client.post("/api/v1/admin/catalog/castings", json=payload)
    assert denied_csrf.status_code == 403

    response = client.post(
        "/api/v1/admin/catalog/castings",
        json=payload,
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-test-token",
        },
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Custom Camaro"
    assert response.json()["description"] == "First verified description"
    casting_id = response.json()["id"]

    with api_factory() as db:
        event = db.scalar(select(ChangeLog).where(ChangeLog.entity_id == casting_id))
        assert event is not None
        assert event.entity_type == "casting"
        assert event.action == "create"
        assert event.actor_type == "user"
        assert event.actor_id == user_id
        assert event.reason == payload["reason"]
        assert event.old_values is None
        assert event.new_values["name"] == "Custom Camaro"

    viewer, _ = authenticated_client(api_factory, permissions=("catalog.read",))
    forbidden = viewer.post(
        "/api/v1/admin/catalog/castings",
        json=payload,
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-test-token",
        },
    )
    assert forbidden.status_code == 403


def test_variant_create_is_scoped_to_existing_casting_and_audited(api_factory):
    with api_factory() as db:
        casting = Casting(name="Custom Camaro")
        db.add(casting)
        db.commit()
        casting_id = casting.id

    client, user_id = authenticated_client(
        api_factory, permissions=("catalog.read", "catalog.create")
    )
    response = client.post(
        f"/api/v1/admin/catalog/castings/{casting_id}/variants",
        json={
            "name": "Opening Hood",
            "description": "Hood opens",
            "reason": "Physical sample inspected",
        },
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-test-token",
        },
    )
    assert response.status_code == 201
    assert response.json()["casting_id"] == casting_id
    variant_id = response.json()["id"]

    with api_factory() as db:
        event = db.scalar(select(ChangeLog).where(ChangeLog.entity_id == variant_id))
        assert event is not None
        assert event.entity_type == "casting_variant"
        assert event.action == "create"
        assert event.actor_id == user_id
        assert event.new_values["casting_id"] == casting_id

    missing = client.post(
        "/api/v1/admin/catalog/castings/missing/variants",
        json={"reason": "Test missing parent"},
        headers={
            "Origin": "https://catalog.example.com",
            "X-CSRF-Token": "csrf-test-token",
        },
    )
    assert missing.status_code == 404


def test_release_create_validates_variant_and_prevents_duplicate_key(api_factory):
    from app.models import CastingVariant

    with api_factory() as db:
        casting = Casting(name="Custom Camaro")
        other = Casting(name="BMW 323")
        db.add_all([casting, other])
        db.flush()
        variant = CastingVariant(casting_id=casting.id, name="Opening Hood")
        foreign_variant = CastingVariant(casting_id=other.id, name="Foreign variant")
        db.add_all([variant, foreign_variant])
        db.commit()
        casting_id = casting.id
        variant_id = variant.id
        foreign_variant_id = foreign_variant.id

    client, user_id = authenticated_client(
        api_factory, permissions=("catalog.read", "catalog.create")
    )
    headers = {
        "Origin": "https://catalog.example.com",
        "X-CSRF-Token": "csrf-test-token",
    }
    payload = {
        "casting_id": casting_id,
        "casting_variant_id": variant_id,
        "catalog_year": 2025,
        "name": "Custom Camaro",
        "assortment_number": "123/250",
        "reason": "Verified against the 2025 catalog",
    }
    invalid = client.post(
        "/api/v1/admin/catalog/releases",
        json={**payload, "casting_variant_id": foreign_variant_id},
        headers=headers,
    )
    assert invalid.status_code == 422

    created = client.post("/api/v1/admin/catalog/releases", json=payload, headers=headers)
    assert created.status_code == 201
    assert created.json()["casting_name"] == "Custom Camaro"
    assert created.json()["casting_variant_name"] == "Opening Hood"
    release_id = created.json()["id"]

    duplicate = client.post("/api/v1/admin/catalog/releases", json=payload, headers=headers)
    assert duplicate.status_code == 409

    with api_factory() as db:
        event = db.scalar(select(ChangeLog).where(ChangeLog.entity_id == release_id))
        assert event is not None
        assert event.entity_type == "release"
        assert event.action == "create"
        assert event.actor_id == user_id
        assert event.new_values["assortment_number"] == "123/250"



def test_series_crud_is_permissioned_and_audited(api_factory):
    client, user_id = authenticated_client(
        api_factory, permissions=("catalog.read", "catalog.create", "catalog.update")
    )
    headers = {"Origin": "https://catalog.example.com", "X-CSRF-Token": "csrf-test-token"}
    denied = client.post("/api/v1/admin/catalog/series", json={
        "name": "Then and Now", "reason": "Verified series"
    })
    assert denied.status_code == 403

    created = client.post("/api/v1/admin/catalog/series", json={
        "name": "  Then and Now  ", "series_type": "Mainline",
        "description": "  Multi-generation pairings  ", "reason": "Verified against catalog"
    }, headers=headers)
    assert created.status_code == 201
    assert created.json()["name"] == "Then and Now"
    assert created.json()["description"] == "Multi-generation pairings"
    series_id = created.json()["id"]

    listed = client.get("/api/v1/admin/catalog/series?q=Then")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == series_id

    updated = client.patch(f"/api/v1/admin/catalog/series/{series_id}", json={
        "status": "confirmed", "reason": "Reviewed by catalog editor"
    }, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["status"] == "confirmed"

    with api_factory() as db:
        events = db.scalars(select(ChangeLog).where(
            ChangeLog.entity_id == series_id
        ).order_by(ChangeLog.created_at)).all()
        assert len(events) == 2
        assert events[0].action == "create"
        assert events[0].actor_id == user_id
        assert events[1].action == "update"
        assert events[1].old_values == {"status": "candidate"}
        assert events[1].new_values == {"status": "confirmed"}


def test_release_series_assignment_is_validated_and_audited(api_factory):
    from app.models import Release, Series

    with api_factory() as db:
        casting = Casting(name="Custom Camaro")
        db.add(casting)
        db.flush()
        release = Release(casting_id=casting.id, catalog_year=2025, name="Custom Camaro")
        series_a = Series(name="Then and Now")
        series_b = Series(name="HW Dream Garage")
        db.add_all([release, series_a, series_b])
        db.commit()
        release_id = release.id
        series_a_id = series_a.id
        series_b_id = series_b.id

    client, user_id = authenticated_client(
        api_factory, permissions=("catalog.read", "catalog.update")
    )
    headers = {"Origin": "https://catalog.example.com", "X-CSRF-Token": "csrf-test-token"}
    invalid = client.put(f"/api/v1/admin/catalog/releases/{release_id}/series", json={
        "series_ids": ["missing"], "reason": "Test invalid series"
    }, headers=headers)
    assert invalid.status_code == 422

    response = client.put(f"/api/v1/admin/catalog/releases/{release_id}/series", json={
        "series_ids": [series_a_id, series_b_id], "reason": "Matched to annual catalog"
    }, headers=headers)
    assert response.status_code == 200
    assert set(response.json()["series_ids"]) == {series_a_id, series_b_id}

    detail = client.get(f"/api/v1/admin/catalog/releases/{release_id}")
    assert {item["id"] for item in detail.json()["series"]} == {series_a_id, series_b_id}

    with api_factory() as db:
        event = db.scalar(select(ChangeLog).where(
            ChangeLog.entity_id == release_id, ChangeLog.action == "update_series"
        ))
        assert event is not None
        assert event.actor_id == user_id
        assert set(event.new_values["series_ids"]) == {series_a_id, series_b_id}


def test_change_history_is_read_permission_protected_and_filterable(api_factory):
    from app.models import Series

    with api_factory() as db:
        series = Series(name="HW Dream Garage")
        db.add(series)
        db.flush()
        db.add(ChangeLog(
            entity_type="series", entity_id=series.id, action="create",
            old_values=None, new_values={"name": series.name},
            reason="Test audit event", actor_type="system",
        ))
        db.commit()

    client, _ = authenticated_client(api_factory, permissions=("catalog.read",))
    response = client.get("/api/v1/admin/catalog/history?entity_type=series&action=create")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["entity_id"] == series.id

    viewer, _ = authenticated_client(api_factory, permissions=())
    assert viewer.get("/api/v1/admin/catalog/history").status_code == 403

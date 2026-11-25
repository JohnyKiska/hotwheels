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
    from app.models import (
        CatalogIdentifier,
        CastingVariant,
        IdentifierType,
        Release,
        ReleaseIdentifier,
        Series,
        ReleaseSeries,
    )

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
        sku_type = IdentifierType(code="sku", label="SKU")
        upc_type = IdentifierType(code="upc", label="UPC")
        db.add_all([sku_type, upc_type])
        db.flush()
        identifiers = [
            CatalogIdentifier(
                identifier_type_id=sku_type.id,
                value=value,
                normalized_value=value,
            )
            for value in ("JBK53", "JBK54")
        ]
        identifiers.append(
            CatalogIdentifier(
                identifier_type_id=upc_type.id,
                value="001234567890",
                normalized_value="001234567890",
            )
        )
        db.add_all(identifiers)
        db.flush()
        db.add_all([
            ReleaseIdentifier(
                release_id=release.id,
                identifier_id=identifier.id,
                role="primary" if identifier.identifier_type_id == sku_type.id else "alternate",
            )
            for identifier in identifiers
        ])
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
    assert {
        (identifier["value"], identifier["type_code"], identifier["role"])
        for identifier in item["identifiers"]
    } == {
        ("JBK53", "sku", "primary"),
        ("JBK54", "sku", "primary"),
        ("001234567890", "upc", "alternate"),
    }

    sku_results = client.get(
        "/api/v1/admin/catalog/releases?q=jbk53&limit=1&offset=0"
    )
    assert sku_results.status_code == 200
    assert sku_results.json()["total"] == 1
    assert [result["id"] for result in sku_results.json()["items"]] == [release_id]

    upc_results = client.get(
        "/api/v1/admin/catalog/releases?q=001234567890"
    )
    assert upc_results.status_code == 200
    assert upc_results.json()["total"] == 1
    assert [result["id"] for result in upc_results.json()["items"]] == [release_id]

    multiple_identifier_matches = client.get(
        "/api/v1/admin/catalog/releases?q=JBK&limit=1&offset=0"
    )
    assert multiple_identifier_matches.status_code == 200
    assert multiple_identifier_matches.json()["total"] == 1
    assert len(multiple_identifier_matches.json()["items"]) == 1
    next_page = client.get(
        "/api/v1/admin/catalog/releases?q=JBK&limit=1&offset=1"
    )
    assert next_page.status_code == 200
    assert next_page.json()["total"] == 1
    assert next_page.json()["items"] == []

    detail = client.get(f"/api/v1/admin/catalog/releases/{release_id}")
    assert detail.status_code == 200
    assert detail.json()["assortment_number"] == "123/250"
    assert detail.json()["identifiers"] == item["identifiers"]

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




def test_release_without_casting_can_be_assigned_and_unassigned_with_audit(api_factory):
    from app.models import CastingVariant, Release

    with api_factory() as db:
        casting = Casting(name="Custom Camaro")
        db.add(casting)
        db.flush()
        variant = CastingVariant(casting_id=casting.id, name="Opening Hood")
        db.add(variant)
        db.commit()
        casting_id = casting.id
        variant_id = variant.id

    client, user_id = authenticated_client(
        api_factory,
        permissions=("catalog.read", "catalog.create", "catalog.update"),
    )
    headers = {
        "Origin": "https://catalog.example.com",
        "X-CSRF-Token": "csrf-test-token",
    }

    payload = {
        "name": "Unassigned Camaro Release",
        "catalog_year": 2025,
        "assortment_number": "321/250",
        "reason": "Verified catalog entry",
    }

    invalid = client.post(
        "/api/v1/admin/catalog/releases",
        json={**payload, "casting_variant_id": variant_id},
        headers=headers,
    )
    assert invalid.status_code == 422

    created = client.post(
        "/api/v1/admin/catalog/releases",
        json=payload,
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["casting_id"] is None
    assert created.json()["casting_name"] is None
    assert created.json()["casting_variant_id"] is None
    release_id = created.json()["id"]

    listed = client.get(
        "/api/v1/admin/catalog/releases?q=Unassigned Camaro Release"
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == release_id
    assert listed.json()["items"][0]["casting_id"] is None

    detail = client.get(f"/api/v1/admin/catalog/releases/{release_id}")
    assert detail.status_code == 200
    assert detail.json()["casting_name"] is None

    assigned = client.patch(
        f"/api/v1/admin/catalog/releases/{release_id}",
        json={
            "casting_id": casting_id,
            "casting_variant_id": variant_id,
            "reason": "Visual identity confirmed",
        },
        headers=headers,
    )
    assert assigned.status_code == 200
    assert assigned.json()["casting_id"] == casting_id
    assert assigned.json()["casting_variant_id"] == variant_id

    unsafe_detach = client.patch(
        f"/api/v1/admin/catalog/releases/{release_id}",
        json={
            "casting_id": None,
            "reason": "Attempt to detach casting only",
        },
        headers=headers,
    )
    assert unsafe_detach.status_code == 422

    detached = client.patch(
        f"/api/v1/admin/catalog/releases/{release_id}",
        json={
            "casting_id": None,
            "casting_variant_id": None,
            "reason": "Remove unverified casting assignment",
        },
        headers=headers,
    )
    assert detached.status_code == 200
    assert detached.json()["casting_id"] is None
    assert detached.json()["casting_variant_id"] is None
    assert detached.json()["casting_name"] is None

    with api_factory() as db:
        events = db.scalars(
            select(ChangeLog).where(
                ChangeLog.entity_type == "release",
                ChangeLog.entity_id == release_id,
            )
        ).all()

        assert any(
            event.action == "create"
            and event.actor_id == user_id
            and event.new_values["casting_id"] is None
            for event in events
        )
        assert any(
            event.old_values == {
                "casting_id": None,
                "casting_variant_id": None,
            }
            and event.new_values == {
                "casting_id": casting_id,
                "casting_variant_id": variant_id,
            }
            for event in events
        )
        assert any(
            event.old_values == {
                "casting_id": casting_id,
                "casting_variant_id": variant_id,
            }
            and event.new_values == {
                "casting_id": None,
                "casting_variant_id": None,
            }
            for event in events
        )

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


def test_product_line_crud_normalizes_checks_uniqueness_and_audits(api_factory):
    client, user_id = authenticated_client(
        api_factory,
        permissions=("catalog.read", "catalog.create", "catalog.update"),
    )
    headers = {
        "Origin": "https://catalog.example.com",
        "X-CSRF-Token": "csrf-test-token",
    }

    denied_csrf = client.post(
        "/api/v1/admin/catalog/product-lines",
        json={
            "code": "PREM",
            "name": "Premium",
            "reason": "Verified taxonomy",
        },
    )
    assert denied_csrf.status_code == 403

    empty_reason = client.post(
        "/api/v1/admin/catalog/product-lines",
        json={
            "code": "PREM",
            "name": "Premium",
            "reason": "   ",
        },
        headers=headers,
    )
    assert empty_reason.status_code == 422

    created = client.post(
        "/api/v1/admin/catalog/product-lines",
        json={
            "code": " PREM ",
            "name": "  Premium   Line  ",
            "description": "  Collectible line  ",
            "reason": "Verified against the catalog",
        },
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["code"] == "prem"
    assert created.json()["name"] == "Premium Line"
    assert created.json()["normalized_name"] == "premium line"
    assert created.json()["description"] == "Collectible line"
    product_line_id = created.json()["id"]

    duplicate_code = client.post(
        "/api/v1/admin/catalog/product-lines",
        json={
            "code": "PREM",
            "name": "Premium Collectibles",
            "reason": "Duplicate code test",
        },
        headers=headers,
    )
    assert duplicate_code.status_code == 409

    duplicate_name = client.post(
        "/api/v1/admin/catalog/product-lines",
        json={
            "code": "premium-collectibles",
            "name": "  PREMIUM LINE ",
            "reason": "Duplicate name test",
        },
        headers=headers,
    )
    assert duplicate_name.status_code == 409

    updated = client.patch(
        f"/api/v1/admin/catalog/product-lines/{product_line_id}",
        json={
            "code": " PREM-LINE ",
            "name": "  Premium   Series ",
            "status": "confirmed",
            "reason": "Reviewed by catalog editor",
        },
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["code"] == "prem-line"
    assert updated.json()["name"] == "Premium Series"
    assert updated.json()["normalized_name"] == "premium series"
    assert updated.json()["status"] == "confirmed"

    with api_factory() as db:
        events = db.scalars(
            select(ChangeLog)
            .where(ChangeLog.entity_id == product_line_id)
            .order_by(ChangeLog.created_at, ChangeLog.id)
        ).all()
        assert [item.action for item in events] == ["create", "update"]
        assert all(item.entity_type == "product_line" for item in events)
        assert all(item.actor_id == user_id for item in events)
        assert events[0].reason == "Verified against the catalog"
        assert events[0].new_values["normalized_name"] == "premium line"
        assert events[1].old_values["normalized_name"] == "premium line"
        assert events[1].new_values["normalized_name"] == "premium series"

    create_denied, _ = authenticated_client(
        api_factory, permissions=("catalog.read",)
    )
    assert create_denied.post(
        "/api/v1/admin/catalog/product-lines",
        json={
            "code": "mainline",
            "name": "Mainline",
            "reason": "Add line",
        },
        headers=headers,
    ).status_code == 403


def test_product_line_list_search_filter_pagination_and_active_release_count(api_factory):
    from app.models import ProductLine, Release, ReleaseProductLine

    with api_factory() as db:
        mainline = ProductLine(
            code="mainline",
            name="Mainline",
            normalized_name="mainline",
            status="confirmed",
        )
        premium = ProductLine(
            code="premium",
            name="Premium",
            normalized_name="premium",
        )
        car_culture = ProductLine(
            code="car-culture",
            name="Car Culture",
            normalized_name="car culture",
        )
        releases = [
            Release(casting=Casting(name=f"Line-count casting {index}"))
            for index in range(4)
        ]
        db.add_all([mainline, premium, car_culture, *releases])
        db.flush()
        db.add_all([
            ReleaseProductLine(release=releases[0], product_line=mainline),
            ReleaseProductLine(
                release=releases[1],
                product_line=mainline,
                membership_status="withdrawn",
            ),
            ReleaseProductLine(release=releases[2], product_line=premium),
            ReleaseProductLine(release=releases[3], product_line=premium),
        ])
        db.commit()

    client, _ = authenticated_client(api_factory, permissions=("catalog.read",))
    by_code = client.get("/api/v1/admin/catalog/product-lines?q=PREM")
    assert by_code.status_code == 200
    assert by_code.json()["total"] == 1
    assert by_code.json()["items"][0]["code"] == "premium"
    assert by_code.json()["items"][0]["release_count"] == 2

    first_page = client.get(
        "/api/v1/admin/catalog/product-lines?status=candidate&limit=1&offset=0"
    )
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 2
    assert first_page.json()["items"][0]["name"] == "Car Culture"
    assert first_page.json()["items"][0]["release_count"] == 0

    second_page = client.get(
        "/api/v1/admin/catalog/product-lines?status=candidate&limit=1&offset=1"
    )
    assert second_page.status_code == 200
    assert second_page.json()["total"] == 2
    assert second_page.json()["items"][0]["name"] == "Premium"
    assert second_page.json()["items"][0]["release_count"] == 2

    confirmed = client.get(
        "/api/v1/admin/catalog/product-lines?status=confirmed"
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 1
    assert confirmed.json()["items"][0]["code"] == "mainline"
    assert confirmed.json()["items"][0]["release_count"] == 1


def test_product_line_detail_includes_parent_children_and_direct_releases(api_factory):
    from app.models import ProductLine, Release, ReleaseProductLine

    with api_factory() as db:
        parent = ProductLine(
            code="premium",
            name="Premium",
            normalized_name="premium",
        )
        child = ProductLine(
            code="car-culture",
            name="Car Culture",
            normalized_name="car culture",
            parent=parent,
        )
        other_line = ProductLine(
            code="mainline",
            name="Mainline",
            normalized_name="mainline",
        )
        release = Release(
            casting=Casting(name="Product-line detail casting"),
            name="Detail release",
            catalog_year=2026,
        )
        db.add_all([child, other_line, release])
        db.flush()
        db.add_all([
            ReleaseProductLine(
                release=release,
                product_line=child,
                membership_status="withdrawn",
            ),
            ReleaseProductLine(release=release, product_line=other_line),
        ])
        parent_id = parent.id
        child_id = child.id
        release_id = release.id
        db.commit()

    client, _ = authenticated_client(api_factory, permissions=("catalog.read",))
    parent_payload = client.get(
        f"/api/v1/admin/catalog/product-lines/{parent_id}"
    )
    assert parent_payload.status_code == 200
    assert [item["id"] for item in parent_payload.json()["children"]] == [child_id]
    assert parent_payload.json()["releases"] == []

    child_payload = client.get(
        f"/api/v1/admin/catalog/product-lines/{child_id}"
    )
    assert child_payload.status_code == 200
    assert child_payload.json()["parent"]["id"] == parent_id
    assert child_payload.json()["releases"] == [{
        "id": release_id,
        "name": "Detail release",
        "catalog_year": 2026,
        "assortment_number": None,
        "status": "candidate",
        "membership_status": "withdrawn",
    }]


def test_product_line_parent_validation_and_cycle_rejection(api_factory):
    from app.models import ProductLine

    client, _ = authenticated_client(
        api_factory,
        permissions=("catalog.read", "catalog.create", "catalog.update"),
    )
    headers = {
        "Origin": "https://catalog.example.com",
        "X-CSRF-Token": "csrf-test-token",
    }
    root = client.post(
        "/api/v1/admin/catalog/product-lines",
        json={
            "code": "premium",
            "name": "Premium",
            "reason": "Create root line",
        },
        headers=headers,
    )
    assert root.status_code == 201
    root_id = root.json()["id"]

    missing_parent = client.post(
        "/api/v1/admin/catalog/product-lines",
        json={
            "code": "missing-parent",
            "name": "Missing Parent",
            "parent_product_line_id": "not-a-line",
            "reason": "Check parent existence",
        },
        headers=headers,
    )
    assert missing_parent.status_code == 422

    child = client.post(
        "/api/v1/admin/catalog/product-lines",
        json={
            "code": "car-culture",
            "name": "Car Culture",
            "parent_product_line_id": root_id,
            "reason": "Create child line",
        },
        headers=headers,
    )
    assert child.status_code == 201
    child_id = child.json()["id"]
    assert child.json()["parent_product_line_id"] == root_id

    self_parent = client.patch(
        f"/api/v1/admin/catalog/product-lines/{root_id}",
        json={
            "parent_product_line_id": root_id,
            "reason": "Reject self-parent",
        },
        headers=headers,
    )
    assert self_parent.status_code == 422

    cycle = client.patch(
        f"/api/v1/admin/catalog/product-lines/{root_id}",
        json={
            "parent_product_line_id": child_id,
            "reason": "Reject hierarchy cycle",
        },
        headers=headers,
    )
    assert cycle.status_code == 422

    with api_factory() as db:
        root_line = db.get(ProductLine, root_id)
        child_line = db.get(ProductLine, child_id)
        assert root_line.parent_product_line_id is None
        assert child_line.parent_product_line_id == root_id


def test_release_product_line_assignment_withdraws_and_is_idempotent(api_factory):
    from app.models import (
        Evidence,
        EvidenceProductLine,
        ProductLine,
        Release,
        ReleaseProductLine,
        Source,
        SourceRecord,
    )

    with api_factory() as db:
        release = Release(casting=Casting(name="Assignment casting"))
        line_a = ProductLine(code="line-a", name="Line A", normalized_name="line a")
        line_b = ProductLine(code="line-b", name="Line B", normalized_name="line b")
        line_c = ProductLine(code="line-c", name="Line C", normalized_name="line c")
        db.add_all([release, line_a, line_b, line_c])
        db.flush()
        assignment_a = ReleaseProductLine(release=release, product_line=line_a)
        assignment_b = ReleaseProductLine(release=release, product_line=line_b)
        evidence = Evidence(
            source_record=SourceRecord(
                source=Source(name="Assignment source", source_type="test"),
                record_type="catalog_entry",
            ),
            attribute_name="product_line",
            observed_value="Line A",
        )
        evidence.product_line_links.append(
            EvidenceProductLine(release_product_line=assignment_a)
        )
        db.add_all([assignment_a, assignment_b, evidence])
        db.commit()
        release_id = release.id
        line_b_id = line_b.id
        line_c_id = line_c.id
        assignment_a_id = assignment_a.id
        evidence_id = evidence.id

    client, user_id = authenticated_client(
        api_factory, permissions=("catalog.read", "catalog.update")
    )
    headers = {
        "Origin": "https://catalog.example.com",
        "X-CSRF-Token": "csrf-test-token",
    }
    route = f"/api/v1/admin/catalog/releases/{release_id}/product-lines"

    duplicate_ids = client.put(
        route,
        json={
            "product_line_ids": [line_b_id, line_b_id],
            "reason": "Reject duplicate IDs",
        },
        headers=headers,
    )
    assert duplicate_ids.status_code == 422

    invalid_id = client.put(
        route,
        json={
            "product_line_ids": ["missing"],
            "reason": "Reject unknown line",
        },
        headers=headers,
    )
    assert invalid_id.status_code == 422

    payload = {
        "product_line_ids": [line_b_id, line_c_id],
        "reason": "Update product-line assignments",
    }
    response = client.put(route, json=payload, headers=headers)
    assert response.status_code == 200
    assert set(response.json()["product_line_ids"]) == {line_b_id, line_c_id}
    assert {
        item["product_line_id"]: item["membership_status"]
        for item in response.json()["assignments"]
    } == {
        next(item["product_line_id"] for item in response.json()["assignments"]
             if item["id"] == assignment_a_id): "withdrawn",
        line_b_id: "active",
        line_c_id: "active",
    }

    repeated = client.put(
        route,
        json={**payload, "reason": "Repeat identical assignment"},
        headers=headers,
    )
    assert repeated.status_code == 200
    assert repeated.json()["product_line_ids"] == response.json()["product_line_ids"]

    with api_factory() as db:
        assignment_a = db.get(ReleaseProductLine, assignment_a_id)
        assert assignment_a.membership_status == "withdrawn"
        assert db.get(
            EvidenceProductLine,
            {
                "evidence_id": evidence_id,
                "release_product_line_id": assignment_a_id,
            },
        ) is not None
        assert db.scalar(
            select(ChangeLog).where(
                ChangeLog.entity_type == "release",
                ChangeLog.entity_id == release_id,
                ChangeLog.action == "update_product_lines",
            )
        ) is not None
        assert db.scalar(
            select(ChangeLog.id).where(
                ChangeLog.entity_id == release_id,
                ChangeLog.action == "update_product_lines",
            )
        ) is not None
        assert len(db.scalars(
            select(ChangeLog).where(
                ChangeLog.entity_id == release_id,
                ChangeLog.action == "update_product_lines",
            )
        ).all()) == 1
        assert len(db.scalars(
            select(ReleaseProductLine).where(
                ReleaseProductLine.release_id == release_id
            )
        ).all()) == 3

    with api_factory() as db:
        event = db.scalar(
            select(ChangeLog).where(
                ChangeLog.entity_id == release_id,
                ChangeLog.action == "update_product_lines",
            )
        )
        assert event.actor_id == user_id
        assert event.reason == payload["reason"]


def test_release_product_line_evidence_attachment_is_audited_and_idempotence_checked(
    api_factory,
):
    from app.models import (
        Evidence,
        EvidenceProductLine,
        EvidenceRelease,
        ProductLine,
        Release,
        ReleaseProductLine,
        Source,
        SourceRecord,
    )

    with api_factory() as db:
        release = Release(casting=Casting(name="Evidence assignment casting"))
        product_line = ProductLine(
            code="evidence-line",
            name="Evidence Line",
            normalized_name="evidence line",
        )
        assignment = ReleaseProductLine(release=release, product_line=product_line)
        evidence = Evidence(
            source_record=SourceRecord(
                source=Source(name="Evidence source", source_type="test"),
                record_type="catalog_entry",
            ),
            attribute_name="product_line",
            observed_value="Evidence Line",
            review_status="manually_verified",
        )
        db.add_all([assignment, evidence])
        db.commit()
        assignment_id = assignment.id
        evidence_id = evidence.id
        source_record_id = evidence.source_record_id

    client, user_id = authenticated_client(
        api_factory, permissions=("catalog.read", "catalog.update")
    )
    headers = {
        "Origin": "https://catalog.example.com",
        "X-CSRF-Token": "csrf-test-token",
    }
    route = f"/api/v1/admin/catalog/release-product-lines/{assignment_id}/evidence"
    payload = {"evidence_id": evidence_id, "reason": "Link reviewed claim"}

    denied_csrf = client.post(route, json=payload)
    assert denied_csrf.status_code == 403

    missing_evidence = client.post(
        route,
        json={**payload, "evidence_id": "missing"},
        headers=headers,
    )
    assert missing_evidence.status_code == 404

    attached = client.post(route, json=payload, headers=headers)
    assert attached.status_code == 201
    assert attached.json() == {
        "evidence_id": evidence_id,
        "release_product_line_id": assignment_id,
        "role": "about",
    }

    duplicate = client.post(route, json=payload, headers=headers)
    assert duplicate.status_code == 409

    with api_factory() as db:
        evidence_after = db.get(Evidence, evidence_id)
        assert evidence_after.attribute_name == "product_line"
        assert evidence_after.observed_value == "Evidence Line"
        assert evidence_after.review_status == "manually_verified"
        assert evidence_after.source_record_id == source_record_id
        assert db.get(
            EvidenceProductLine,
            {
                "evidence_id": evidence_id,
                "release_product_line_id": assignment_id,
            },
        ) is not None
        assert db.scalar(
            select(EvidenceRelease).where(EvidenceRelease.evidence_id == evidence_id)
        ) is None
        event = db.scalar(
            select(ChangeLog).where(
                ChangeLog.entity_type == "release_product_line",
                ChangeLog.entity_id == assignment_id,
                ChangeLog.action == "attach_evidence",
            )
        )
        assert event is not None
        assert event.actor_id == user_id
        assert event.reason == payload["reason"]
        assert event.new_values == {"evidence_id": evidence_id, "role": "about"}


def test_release_payload_includes_direct_product_lines_and_membership_status(api_factory):
    from app.models import ProductLine, Release, ReleaseProductLine

    with api_factory() as db:
        release = Release(casting=Casting(name="Payload casting"), name="Payload release")
        active_line = ProductLine(
            code="active-line",
            name="Active Line",
            normalized_name="active line",
            status="confirmed",
        )
        withdrawn_line = ProductLine(
            code="withdrawn-line",
            name="Withdrawn Line",
            normalized_name="withdrawn line",
        )
        db.add_all([release, active_line, withdrawn_line])
        db.flush()
        db.add_all([
            ReleaseProductLine(release=release, product_line=active_line),
            ReleaseProductLine(
                release=release,
                product_line=withdrawn_line,
                membership_status="withdrawn",
            ),
        ])
        db.commit()
        release_id = release.id

    client, _ = authenticated_client(api_factory, permissions=("catalog.read",))
    detail = client.get(f"/api/v1/admin/catalog/releases/{release_id}")
    assert detail.status_code == 200
    assert detail.json()["product_lines"] == [
        {
            "id": active_line.id,
            "code": "active-line",
            "name": "Active Line",
            "status": "confirmed",
            "membership_status": "active",
        },
        {
            "id": withdrawn_line.id,
            "code": "withdrawn-line",
            "name": "Withdrawn Line",
            "status": "candidate",
            "membership_status": "withdrawn",
        },
    ]
    assert detail.json()["series"] == []

    listed = client.get("/api/v1/admin/catalog/releases")
    assert listed.status_code == 200
    item = next(row for row in listed.json()["items"] if row["id"] == release_id)
    assert item["product_lines"] == detail.json()["product_lines"]


def test_release_list_product_line_payload_uses_selectin_loading(api_factory):
    from app.models import ProductLine, Release, ReleaseProductLine

    with api_factory() as db:
        product_line = ProductLine(
            code="shared-line",
            name="Shared Line",
            normalized_name="shared line",
        )
        releases = [
            Release(
                casting=Casting(name=f"Select-in casting {index}"),
                name=f"Select-in release {index}",
            )
            for index in range(4)
        ]
        db.add_all([product_line, *releases])
        db.flush()
        db.add_all([
            ReleaseProductLine(release=release, product_line=product_line)
            for release in releases
        ])
        db.commit()

    client, _ = authenticated_client(api_factory, permissions=("catalog.read",))
    engine = api_factory.kw["bind"]
    statements = []

    def capture_select(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture_select)
    try:
        response = client.get("/api/v1/admin/catalog/releases?limit=10")
    finally:
        event.remove(engine, "before_cursor_execute", capture_select)

    assert response.status_code == 200
    assert response.json()["total"] == 4
    assert sum("from release_product_lines" in item for item in statements) == 1
    assert sum("from product_lines" in item for item in statements) == 1

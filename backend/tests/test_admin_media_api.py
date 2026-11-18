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
    ChangeLog, Evidence, MediaAsset, MediaAssetEvidence, Permission, Role,
    RolePermission, Source, SourceRecord, User, UserRole,
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


def authenticated_client(factory, permissions=("catalog.read", "catalog.create", "catalog.update")):
    with factory() as db:
        user = User(status="active", display_name="Media admin")
        role = Role(code=f"media_admin_{uuid.uuid4().hex[:12]}", name="Media admin")
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
        _session, token = create_session(db, user_id=user.id)
        user_id = user.id
        db.commit()
    client = TestClient(app)
    client.cookies.set("hw_session", token)
    client.cookies.set("hw_csrf", "csrf-media-token")
    headers = {"Origin": "https://catalog.example.com", "X-CSRF-Token": "csrf-media-token"}
    return client, user_id, headers


def test_media_source_record_and_asset_creation_are_audited(api_factory):
    client, user_id, headers = authenticated_client(api_factory)
    source = client.post(
        "/api/v1/admin/media/sources",
        json={"name": "eBay", "source_type": "marketplace", "base_url": "https://www.ebay.com", "reason": "Register eBay as a source"},
        headers=headers,
    )
    assert source.status_code == 200
    source_id = source.json()["id"]

    record = client.post(
        "/api/v1/admin/media/records",
        json={
            "source_id": source_id,
            "external_id": "123456789",
            "record_url": "https://www.ebay.com/itm/123456789",
            "record_type": "listing",
            "reason": "Pilot listing captured for blister reference",
        },
        headers=headers,
    )
    assert record.status_code == 200
    record_id = record.json()["id"]

    asset = client.post(
        "/api/v1/admin/media/assets",
        json={
            "source_record_id": record_id,
            "storage_key": "images/sha256/" + "a" * 64 + ".jpg",
            "original_filename": "blister-front.jpg",
            "mime_type": "image/jpeg",
            "checksum_sha256": "a" * 64,
            "category": "package_photo",
            "angle": "package_front",
            "rights_status": "unknown",
            "width": 1600,
            "height": 1200,
            "byte_size": 245000,
            "reason": "Register source image metadata",
        },
        headers=headers,
    )
    assert asset.status_code == 200
    asset_id = asset.json()["id"]

    with api_factory() as db:
        stored = db.get(MediaAsset, asset_id)
        assert stored.uploader_user_id == user_id
        assert stored.category == "package_photo"
        assert stored.angle == "package_front"
        events = db.scalars(select(ChangeLog).where(ChangeLog.entity_id.in_([source_id, record_id, asset_id]))).all()
        assert len(events) == 3
        assert all(event.actor_id == user_id for event in events)


def test_media_asset_list_filters_and_duplicate_checksum(api_factory):
    with api_factory() as db:
        source = Source(name="eBay", source_type="marketplace")
        record = SourceRecord(source=source, external_id="listing-1", record_type="listing")
        asset = MediaAsset(
            source_record=record, storage_key="images/one.jpg",
            checksum_sha256="b" * 64, category="package_photo",
            angle="package_back", rights_status="unknown",
        )
        db.add(asset)
        db.commit()
        record_id = record.id

    client, _, headers = authenticated_client(api_factory)
    listed = client.get("/api/v1/admin/media/assets?category=package_photo&angle=package_back")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["external_id"] == "listing-1"

    duplicate = client.post(
        "/api/v1/admin/media/assets",
        json={
            "source_record_id": record_id,
            "storage_key": "images/duplicate.jpg",
            "checksum_sha256": "b" * 64,
            "reason": "Duplicate test",
        },
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["existing_asset_id"] == listed.json()["items"][0]["id"]


def test_media_patch_requires_csrf_and_records_rights_change(api_factory):
    with api_factory() as db:
        source = Source(name="eBay", source_type="marketplace")
        record = SourceRecord(source=source, record_type="listing")
        asset = MediaAsset(source_record=record, storage_key="images/rights.jpg", checksum_sha256="c" * 64)
        db.add(asset)
        db.commit()
        asset_id = asset.id

    client, user_id, headers = authenticated_client(api_factory)
    payload = {"rights_status": "permitted", "rights_holder": "Photographer", "reason": "Written permission received"}
    denied = client.patch(f"/api/v1/admin/media/assets/{asset_id}", json=payload)
    assert denied.status_code == 403

    response = client.patch(f"/api/v1/admin/media/assets/{asset_id}", json=payload, headers=headers)
    assert response.status_code == 200

    with api_factory() as db:
        stored = db.get(MediaAsset, asset_id)
        assert stored.rights_status == "permitted"
        event = db.scalar(select(ChangeLog).where(ChangeLog.entity_id == asset_id))
        assert event.actor_id == user_id
        assert event.old_values == {"rights_status": "unknown", "rights_holder": None}
        assert event.new_values == {"rights_status": "permitted", "rights_holder": "Photographer"}


def test_media_storage_key_rejects_traversal_and_unknown_fields(api_factory):
    with api_factory() as db:
        source = Source(name="Local", source_type="user_upload")
        record = SourceRecord(source=source, record_type="photo")
        db.add(record)
        db.commit()
        record_id = record.id

    client, _, headers = authenticated_client(api_factory)
    payload = {
        "source_record_id": record_id, "storage_key": "../outside.jpg",
        "checksum_sha256": "d" * 64, "reason": "Unsafe path test",
    }
    unsafe = client.post("/api/v1/admin/media/assets", json=payload, headers=headers)
    assert unsafe.status_code == 422

    payload["storage_key"] = "images/safe.jpg"
    payload["actor_id"] = "spoofed"
    spoofed = client.post("/api/v1/admin/media/assets", json=payload, headers=headers)
    assert spoofed.status_code == 422


def test_media_asset_can_link_to_evidence(api_factory):
    with api_factory() as db:
        source = Source(name="Catalog", source_type="web")
        record = SourceRecord(source=source, record_type="listing")
        asset = MediaAsset(source_record=record, storage_key="images/evidence.jpg", checksum_sha256="e" * 64)
        evidence = Evidence(source_record=record, attribute_name="collector_number", observed_value="123/250")
        db.add_all([asset, evidence])
        db.commit()
        asset_id, evidence_id = asset.id, evidence.id

    client, _, headers = authenticated_client(api_factory)
    linked = client.post(
        f"/api/v1/admin/media/assets/{asset_id}/evidence",
        json={"evidence_id": evidence_id, "role": "supports", "reason": "This image supports the observed number"},
        headers=headers,
    )
    assert linked.status_code == 200

    with api_factory() as db:
        link = db.get(MediaAssetEvidence, {"media_asset_id": asset_id, "evidence_id": evidence_id})
        assert link is not None
        assert link.role == "supports"

from io import BytesIO
from pathlib import Path

from PIL import Image


def _png_image_bytes(size=(800, 600)):
    output = BytesIO()
    Image.new("RGB", size, (220, 40, 30)).save(output, format="PNG")
    return output.getvalue()


def test_media_upload_preserves_original_and_generates_thumbnail(api_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("HW_CATALOG_MEDIA_DIR", str(tmp_path / "media"))
    with api_factory() as db:
        source = Source(name="eBay", source_type="marketplace")
        record = SourceRecord(source=source, external_id="listing-upload-1", record_type="listing")
        db.add(record)
        db.commit()
        record_id = record.id

    client, user_id, headers = authenticated_client(api_factory)
    original = _png_image_bytes()
    response = client.post(
        "/api/v1/admin/media/upload",
        data={
            "source_record_id": record_id,
            "category": "package_photo",
            "angle": "package_front",
            "rights_status": "unknown",
            "reason": "Add eBay blister-front reference image",
        },
        files={"file": ("blister-front.png", original, "image/png")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mime_type"] == "image/png"
    assert payload["byte_size"] == len(original)
    assert payload["category"] == "package_photo"
    assert payload["angle"] == "package_front"
    assert payload["rights_status"] == "unknown"
    assert payload["uploader_user_id"] == user_id

    original_response = client.get(payload["file_url"])
    assert original_response.status_code == 200
    assert original_response.content == original
    assert original_response.headers["content-type"] == "image/png"

    thumbnail_response = client.get(payload["thumbnail_url"])
    assert thumbnail_response.status_code == 200
    assert thumbnail_response.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(thumbnail_response.content)) as thumbnail:
        assert thumbnail.format == "WEBP"
        assert thumbnail.width <= 640
        assert thumbnail.height <= 640

    duplicate = client.post(
        "/api/v1/admin/media/upload",
        data={
            "source_record_id": record_id,
            "reason": "Try to add the same image twice",
        },
        files={"file": ("duplicate.png", original, "image/png")},
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["existing_asset_id"] == payload["id"]

    with api_factory() as db:
        stored = db.get(MediaAsset, payload["id"])
        assert stored is not None
        assert stored.uploader_user_id == user_id
        audit = db.scalar(select(ChangeLog).where(ChangeLog.entity_id == payload["id"]))
        assert audit.action == "upload"
        assert audit.actor_id == user_id


def test_media_upload_rejects_invalid_and_mismatched_content(api_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("HW_CATALOG_MEDIA_DIR", str(tmp_path / "media"))
    with api_factory() as db:
        source = Source(name="Local", source_type="user_upload")
        record = SourceRecord(source=source, record_type="photo")
        db.add(record)
        db.commit()
        record_id = record.id

    client, _, headers = authenticated_client(api_factory)
    invalid = client.post(
        "/api/v1/admin/media/upload",
        data={"source_record_id": record_id, "reason": "Reject non-image payload"},
        files={"file": ("payload.txt", b"not an image", "text/plain")},
        headers=headers,
    )
    assert invalid.status_code == 422

    mismatch = client.post(
        "/api/v1/admin/media/upload",
        data={"source_record_id": record_id, "reason": "Reject incorrect content type"},
        files={"file": ("payload.png", _png_image_bytes(), "image/jpeg")},
        headers=headers,
    )
    assert mismatch.status_code == 415
    assert not list((tmp_path / "media").rglob("*.png"))


def test_media_upload_enforces_size_limit(api_factory, tmp_path, monkeypatch):
    from app.media_storage import MAX_IMAGE_BYTES

    monkeypatch.setenv("HW_CATALOG_MEDIA_DIR", str(tmp_path / "media"))
    with api_factory() as db:
        source = Source(name="Local", source_type="user_upload")
        record = SourceRecord(source=source, record_type="photo")
        db.add(record)
        db.commit()
        record_id = record.id

    client, _, headers = authenticated_client(api_factory)
    response = client.post(
        "/api/v1/admin/media/upload",
        data={"source_record_id": record_id, "reason": "Reject oversized image"},
        files={"file": ("large.png", b"x" * (MAX_IMAGE_BYTES + 1), "image/png")},
        headers=headers,
    )
    assert response.status_code == 413

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    Casting,
    CatalogIdentifier,
    Evidence,
    EvidenceRelease,
    IdentifierType,
    Release,
    ReleaseIdentifier,
    ReleaseSeries,
    Series,
    Source,
    SourceRecord,
)


def make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def seed_catalog(engine):
    with Session(engine) as session:
        casting_a = Casting(name="Mazda Autozam", status="candidate")
        casting_b = Casting(name="Nissan Skyline", status="candidate")
        series = Series(name="HW J-Imports", status="candidate")
        session.add_all([casting_a, casting_b, series])
        session.flush()

        releases = [
            Release(id="release-auto", casting_id=casting_a.id, name="Mazda Autozam",
                    catalog_year=2024, status="candidate"),
            Release(id="release-skyline", casting_id=casting_b.id, name="Nissan Skyline",
                    catalog_year=2024, status="candidate"),
        ]
        session.add_all(releases)
        session.flush()
        session.add(ReleaseSeries(release_id="release-auto", series_id=series.id))

        sku_type = IdentifierType(code="sku", label="SKU")
        col_type = IdentifierType(code="catalog_number", label="Catalog number")
        session.add_all([sku_type, col_type])
        session.flush()

        identifiers = [
            (sku_type, "HRY51", "release-auto", "primary"),
            (col_type, "001", "release-auto", "secondary"),
            (sku_type, "HTC65", "release-skyline", "primary"),
            (col_type, "191", "release-skyline", "secondary"),
        ]
        for kind, value, release_id, role in identifiers:
            identifier = CatalogIdentifier(
                identifier_type_id=kind.id,
                value=value,
                normalized_value=value,
            )
            session.add(identifier)
            session.flush()
            session.add(ReleaseIdentifier(
                release_id=release_id,
                identifier_id=identifier.id,
                role=role,
            ))

        source = Source(name="Hot Wheels Wiki", source_type="website")
        session.add(source)
        session.flush()
        for release_id, attribute, value in [
            ("release-auto", "collector_number", "001"),
            ("release-skyline", "collector_number", "191"),
        ]:
            source_record = SourceRecord(
                source_id=source.id,
                record_type="mainline_release_row",
                record_url="https://example.test/catalog",
                external_id=release_id,
                raw_data={"release_id": release_id},
            )
            session.add(source_record)
            session.flush()
            evidence = Evidence(
                source_record_id=source_record.id,
                attribute_name=attribute,
                observed_value=value,
                assessment="supports",
                review_status="pending",
            )
            session.add(evidence)
            session.flush()
            session.add(EvidenceRelease(
                evidence_id=evidence.id,
                release_id=release_id,
                role="about",
            ))
        session.commit()


def override_database(engine):
    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db


def test_live_admin_page_is_served_from_backend():
    response = TestClient(app).get("/admin")
    assert response.status_code == 200
    assert "живая база" in response.text
    assert "fetch(" in response.text


def test_catalog_admin_summary_and_release_search_are_read_only():
    engine = make_engine()
    seed_catalog(engine)
    override_database(engine)
    try:
        client = TestClient(app)
        summary = client.get("/catalog/admin/summary")
        assert summary.status_code == 200
        assert summary.json()["writes_to_catalog"] is False
        assert summary.json()["totals"] == {
            "releases": 2,
            "castings": 2,
            "series": 1,
            "source_records": 2,
            "evidence": 2,
            "identifiers": 4,
        }

        response = client.get(
            "/catalog/admin/releases",
            params={"q": "HRY51", "catalog_year": 2024, "limit": 10},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["writes_to_catalog"] is False
        assert payload["total"] == 1
        assert payload["items"][0]["id"] == "release-auto"
        assert payload["items"][0]["sku"] == ["HRY51"]
        assert payload["items"][0]["catalog_numbers"] == ["001"]
        assert payload["items"][0]["series"] == ["HW J-Imports"]

        filtered = client.get(
            "/catalog/admin/releases",
            params={"status": "candidate", "offset": 1, "limit": 1},
        )
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 2
        assert len(filtered.json()["items"]) == 1

        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Release)) == 2
            assert session.scalar(select(func.count()).select_from(Evidence)) == 2
            assert session.scalar(select(func.count()).select_from(ReleaseIdentifier)) == 4
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_catalog_admin_release_detail_includes_evidence_and_source_provenance():
    engine = make_engine()
    seed_catalog(engine)
    override_database(engine)
    try:
        response = TestClient(app).get("/catalog/admin/releases/release-auto")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["release"]["name"] == "Mazda Autozam"
    assert payload["casting"]["name"] == "Mazda Autozam"
    assert payload["identifiers"][0]["type"] in {"catalog_number", "sku"}
    assert payload["series"] == ["HW J-Imports"]
    assert len(payload["evidence"]) == 1
    assert payload["evidence"][0]["attribute"] == "collector_number"
    assert payload["evidence"][0]["review_status"] == "pending"
    assert payload["evidence"][0]["source"] == "Hot Wheels Wiki"
    assert payload["evidence"][0]["raw_data"] == {"release_id": "release-auto"}


def test_catalog_admin_returns_404_for_unknown_release():
    engine = make_engine()
    override_database(engine)
    try:
        response = TestClient(app).get("/catalog/admin/releases/not-a-release")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 404

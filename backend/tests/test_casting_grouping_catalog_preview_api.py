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


def override_database(engine):
    def override_get_db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db


def test_catalog_grouping_preview_uses_release_sku_and_collector_evidence_without_writes():
    engine = make_engine()
    with Session(engine) as session:
        casting_a = Casting(name="Same Model", status="candidate")
        casting_b = Casting(name="Same Model", status="candidate")
        casting_c = Casting(name="No Number", status="candidate")
        session.add_all([casting_a, casting_b, casting_c])
        session.flush()

        releases = [
            Release(id="release-a", casting_id=casting_a.id, name="Same Model",
                    catalog_year=2024, status="candidate"),
            Release(id="release-b", casting_id=casting_b.id, name="Same Model",
                    catalog_year=2024, status="candidate"),
            Release(id="release-c", casting_id=casting_c.id, name="No Number",
                    catalog_year=2024, status="candidate"),
        ]
        session.add_all(releases)
        session.flush()

        sku_type = IdentifierType(code="sku", label="SKU")
        session.add(sku_type)
        session.flush()
        for release_id, sku in [("release-a", "AAA01"), ("release-b", "BBB02")]:
            identifier = CatalogIdentifier(
                identifier_type_id=sku_type.id,
                value=sku,
                normalized_value=sku,
            )
            session.add(identifier)
            session.flush()
            session.add(ReleaseIdentifier(
                release_id=release_id,
                identifier_id=identifier.id,
                role="primary",
            ))

        source = Source(name="Synthetic source", source_type="test")
        session.add(source)
        session.flush()
        for release_id, col_number in [("release-a", "001"), ("release-b", "001")]:
            source_record = SourceRecord(
                source_id=source.id,
                record_type="catalog_item",
                raw_data={},
            )
            session.add(source_record)
            session.flush()
            evidence = Evidence(
                source_record_id=source_record.id,
                attribute_name="collector_number",
                observed_value=col_number,
            )
            session.add(evidence)
            session.flush()
            session.add(EvidenceRelease(
                evidence_id=evidence.id,
                release_id=release_id,
                role="about",
            ))
        session.commit()

    override_database(engine)
    try:
        response = TestClient(app).post(
            "/castings/grouping-preview/from-catalog",
            json={"product_line": "Mainline", "catalog_year": 2024},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "preview_only"
    assert payload["writes_to_catalog"] is False
    assert payload["catalog_snapshot"] == {
        "product_line": "Mainline",
        "catalog_year": 2024,
        "records_loaded": 3,
        "source": "catalog_database",
    }
    assert len(payload["groups"]) == 1
    group = payload["groups"][0]
    assert group["group_key"] == {
        "product_line": "Mainline",
        "catalog_year": 2024,
        "collector_number": "001",
    }
    assert {item["sku"][0] for item in group["records"]} == {"AAA01", "BBB02"}
    assert payload["manual_review"][0]["record_id"] == "release-c"
    assert "missing_collector_number" in payload["manual_review"][0]["reason_codes"]

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Release)) == 3
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(ReleaseIdentifier)) == 2


def test_catalog_grouping_preview_requires_explicit_product_line():
    engine = make_engine()
    override_database(engine)
    try:
        response = TestClient(app).post(
            "/castings/grouping-preview/from-catalog",
            json={"product_line": "   "},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422

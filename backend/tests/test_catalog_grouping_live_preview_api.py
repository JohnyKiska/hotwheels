from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    Casting, CatalogIdentifier, Evidence, EvidenceRelease, IdentifierType,
    Release, ReleaseIdentifier, Source, SourceRecord,
)


def make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_catalog_grouping_preview_splits_one_legacy_casting_by_collector_number_without_writes():
    engine = make_engine()
    with Session(engine) as session:
        legacy = Casting(name="Nissan Skyline 2000GT-R LBWK", status="candidate")
        session.add(legacy)
        session.flush()
        releases = [
            Release(id="release-tooned", casting_id=legacy.id, name="Nissan Skyline 2000GT-R LBWK",
                    catalog_year=2024, status="candidate"),
            Release(id="release-then-now", casting_id=legacy.id, name="Nissan Skyline 2000GT-R LBWK",
                    catalog_year=2024, status="candidate"),
        ]
        session.add_all(releases)
        session.flush()
        sku_type = IdentifierType(code="sku", label="SKU")
        session.add(sku_type)
        session.flush()
        source = Source(name="Test source", source_type="test")
        session.add(source)
        session.flush()
        for release_id, sku, col in [
            ("release-tooned", "HRY85", "213"),
            ("release-then-now", "HTC65", "191"),
        ]:
            identifier = CatalogIdentifier(
                identifier_type_id=sku_type.id, value=sku, normalized_value=sku
            )
            session.add(identifier)
            session.flush()
            session.add(ReleaseIdentifier(
                release_id=release_id, identifier_id=identifier.id, role="primary"
            ))
            source_record = SourceRecord(
                source_id=source.id, record_type="catalog_item", raw_data={}
            )
            session.add(source_record)
            session.flush()
            evidence = Evidence(
                source_record_id=source_record.id,
                attribute_name="collector_number",
                observed_value=col,
                review_status="pending",
            )
            session.add(evidence)
            session.flush()
            session.add(EvidenceRelease(
                evidence_id=evidence.id, release_id=release_id, role="about"
            ))
        session.commit()
        original_casting_id = legacy.id

    def override_get_db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db
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
    assert payload["summary"]["records_received"] == 2
    assert payload["summary"]["proposed_groups"] == 2
    assert payload["summary"]["conflicts"] == 1
    groups = {g["group_key"]["collector_number"]: g for g in payload["groups"]}
    assert set(groups) == {"191", "213"}
    assert groups["191"]["records"][0]["sku"] == ["HTC65"]
    assert groups["213"]["records"][0]["sku"] == ["HRY85"]
    assert all(g["requires_manual_review"] for g in groups.values())
    assert payload["conflicts"][0]["existing_casting_id"] == original_casting_id

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Release)) == 2
        assert session.scalar(select(func.count()).select_from(Casting)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2

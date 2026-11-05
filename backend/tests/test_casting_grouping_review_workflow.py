from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    Casting, CatalogIdentifier, Evidence, EvidenceRelease, IdentifierType,
    Release, ReleaseIdentifier, Source, SourceRecord,
    CastingGroupingReviewDecision, CastingGroupingReviewSession,
)


def make_review_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        casting = Casting(name="Mazda Autozam", status="candidate")
        db.add(casting)
        db.flush()
        release = Release(
            id="review-release-1", casting_id=casting.id, name="Mazda Autozam",
            catalog_year=2024, status="candidate",
        )
        sku_type = IdentifierType(code="sku", label="SKU")
        db.add_all([release, sku_type])
        db.flush()
        sku = CatalogIdentifier(
            identifier_type_id=sku_type.id, value="HRY51", normalized_value="HRY51"
        )
        db.add(sku)
        db.flush()
        db.add(ReleaseIdentifier(
            release_id=release.id, identifier_id=sku.id, role="primary"
        ))
        source = Source(name="Review test source", source_type="test")
        db.add(source)
        db.flush()
        source_record = SourceRecord(
            source_id=source.id, record_type="catalog_item", raw_data={}
        )
        db.add(source_record)
        db.flush()
        evidence = Evidence(
            source_record_id=source_record.id,
            attribute_name="collector_number",
            observed_value="001",
            review_status="pending",
        )
        db.add(evidence)
        db.flush()
        db.add(EvidenceRelease(
            evidence_id=evidence.id, release_id=release.id, role="about"
        ))
        db.commit()
    return engine


def install_review_db_override(engine):
    def override_get_db():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = override_get_db


def test_review_session_persists_snapshot_and_append_only_decision_history():
    engine = make_review_engine()
    install_review_db_override(engine)
    client = TestClient(app)
    try:
        created = client.post(
            "/castings/grouping-review-sessions/from-catalog",
            json={"product_line": "Mainline", "catalog_year": 2024},
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["writes_to_catalog"] is False
        assert payload["stale"] is False
        session_id = payload["session_id"]
        proposal_id = payload["snapshot"]["remediation_plan"]["items"][0]["proposal_id"]

        first = client.post(
            f"/castings/grouping-review-sessions/{session_id}/decisions",
            json={
                "proposal_id": proposal_id,
                "disposition": "needs_more_evidence",
                "reviewer_label": "operator",
                "reason": "Evidence is still pending.",
            },
        )
        assert first.status_code == 200
        first_decision = first.json()["decision"]
        assert first_decision["previous_decision_id"] is None

        second = client.post(
            f"/castings/grouping-review-sessions/{session_id}/decisions",
            json={
                "proposal_id": proposal_id,
                "disposition": "accepted",
                "reviewer_label": "operator",
                "reason": "Reviewed again.",
            },
        )
        assert second.status_code == 200
        assert second.json()["decision"]["previous_decision_id"] == first_decision["id"]

        history = client.get(
            f"/castings/grouping-review-sessions/{session_id}/decisions"
        )
        assert history.status_code == 200
        assert history.json()["total"] == 2
        assert [item["disposition"] for item in history.json()["items"]] == [
            "needs_more_evidence", "accepted"
        ]

        detail = client.get(f"/castings/grouping-review-sessions/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["decisions"][0]["disposition"] == "accepted"

        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(CastingGroupingReviewSession)) == 1
            assert db.scalar(select(func.count()).select_from(CastingGroupingReviewDecision)) == 2
            assert db.scalar(select(func.count()).select_from(Casting)) == 1
            assert db.scalar(select(func.count()).select_from(Release)) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_review_session_rejects_unknown_proposal_and_stale_decisions():
    engine = make_review_engine()
    install_review_db_override(engine)
    client = TestClient(app)
    try:
        created = client.post(
            "/castings/grouping-review-sessions/from-catalog",
            json={"product_line": "Mainline", "catalog_year": 2024},
        )
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        unknown = client.post(
            f"/castings/grouping-review-sessions/{session_id}/decisions",
            json={
                "proposal_id": "not-in-snapshot",
                "disposition": "accepted",
                "reviewer_label": "operator",
            },
        )
        assert unknown.status_code == 404

        with Session(engine) as db:
            evidence = db.scalar(select(Evidence))
            evidence.observed_value = "002"
            db.commit()

        stale_detail = client.get(
            f"/castings/grouping-review-sessions/{session_id}"
        )
        assert stale_detail.status_code == 200
        assert stale_detail.json()["stale"] is True

        stale_decision = client.post(
            f"/castings/grouping-review-sessions/{session_id}/decisions",
            json={
                "proposal_id": created.json()["snapshot"]["remediation_plan"]["items"][0]["proposal_id"],
                "disposition": "accepted",
                "reviewer_label": "operator",
            },
        )
        assert stale_decision.status_code == 409
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(CastingGroupingReviewDecision)) == 0
    finally:
        app.dependency_overrides.pop(get_db, None)

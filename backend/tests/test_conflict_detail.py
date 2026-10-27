from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.conflict_queue import get_conflict_detail
from app.db import Base
from app.models import Conflict, ConflictEvidence, Evidence, Source, SourceRecord


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_detail_includes_claim_and_source_snapshot_without_mutation():
    with make_session() as session:
        source = Source(
            name="Official catalog",
            source_type="website",
            base_url="https://example.test",
            publisher="Mattel",
            is_official=True,
            access_status="available",
        )
        session.add(source)
        session.flush()
        record = SourceRecord(
            source_id=source.id,
            record_type="catalog_entry",
            record_url="https://example.test/car/42",
            external_id="42",
        )
        session.add(record)
        session.flush()
        evidence = Evidence(
            source_record_id=record.id,
            attribute_name="wheel_type",
            observed_value="PR5",
            evidence_type="text",
            assessment="supports",
            review_status="pending",
        )
        conflict = Conflict(
            conflict_type="evidence_disagreement",
            status="open",
            severity="medium",
            attribute_name="evidence_disagreement:wheel_type",
        )
        session.add_all([evidence, conflict])
        session.flush()
        session.add(ConflictEvidence(
            conflict_id=conflict.id,
            evidence_id=evidence.id,
            role="conflicting_claim",
            note="Observed in catalog entry",
        ))
        session.flush()

        result = get_conflict_detail(session, conflict.id)

        assert result["id"] == conflict.id
        assert result["status"] == "open"
        assert result["evidence"][0]["observed_value"] == "PR5"
        assert result["evidence"][0]["source_name"] == "Official catalog"
        assert result["evidence"][0]["source_is_official"] is True
        assert result["evidence"][0]["record_url"] == "https://example.test/car/42"
        assert conflict.status == "open"
        assert evidence.review_status == "pending"


def test_detail_returns_none_for_unknown_conflict():
    with make_session() as session:
        assert get_conflict_detail(session, "missing-conflict-id") is None

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.conflict_queue import list_conflicts
from app.db import Base
from app.models import Conflict, ConflictEvidence, Evidence, EvidenceRelease, Release, Casting, Source, SourceRecord


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_conflict(session, *, status="open", severity="medium", conflict_type="evidence_disagreement"):
    conflict = Conflict(conflict_type=conflict_type, status=status, severity=severity, attribute_name="wheel_type")
    session.add(conflict)
    session.flush()
    source = Source(name="Example source", source_type="website", access_status="available")
    session.add(source)
    session.flush()
    record = SourceRecord(source_id=source.id, record_type="catalog_entry", record_url="https://example.test/car/1")
    session.add(record)
    session.flush()
    evidence = Evidence(source_record_id=record.id, attribute_name="wheel_type", observed_value="PR5", assessment="supports", review_status="pending")
    session.add(evidence)
    session.flush()
    session.add(ConflictEvidence(conflict_id=conflict.id, evidence_id=evidence.id, role="conflicting_claim"))
    session.flush()
    return conflict, evidence


def test_default_queue_only_contains_open_and_under_review_and_includes_source_evidence():
    with make_session() as session:
        open_conflict, evidence = seed_conflict(session, status="open")
        seed_conflict(session, status="under_review", severity="high")
        seed_conflict(session, status="resolved")
        session.flush()

        result = list_conflicts(session)
        assert result["total"] == 2
        assert {item["status"] for item in result["items"]} == {"open", "under_review"}
        item = next(item for item in result["items"] if item["id"] == open_conflict.id)
        assert item["evidence"][0]["evidence_id"] == evidence.id
        assert item["evidence"][0]["source_name"] == "Example source"
        assert item["evidence"][0]["observed_value"] == "PR5"


def test_filters_and_pagination_are_applied_without_mutating_records():
    with make_session() as session:
        selected, evidence = seed_conflict(session, severity="high", conflict_type="identifier_collision")
        seed_conflict(session, severity="medium")
        result = list_conflicts(session, severity="high", conflict_type="identifier_collision", limit=1)
        assert result["total"] == 1
        assert result["items"][0]["id"] == selected.id
        assert evidence.review_status == "pending"
        assert selected.status == "open"
        assert session.scalar(select(func.count()).select_from(ConflictEvidence)) == 2


def test_invalid_filters_and_pagination_are_rejected():
    with make_session() as session:
        for kwargs in ({"status": "unknown"}, {"severity": "urgent"}, {"limit": 0}, {"limit": 101}, {"offset": -1}, {"conflict_type": "  "}):
            try:
                list_conflicts(session, **kwargs)
            except ValueError:
                pass
            else:
                raise AssertionError(f"expected ValueError for {kwargs}")



def test_release_traceability_is_additive_for_legacy_conflicts_without_release_links():
    from app.conflict_queue import get_conflict_detail

    with make_session() as session:
        conflict, evidence = seed_conflict(session)
        session.flush()

        listed = list_conflicts(session)
        item = next(row for row in listed["items"] if row["id"] == conflict.id)
        detail = get_conflict_detail(session, conflict.id)

        # Existing top-level fields remain available for older API consumers.
        legacy_fields = {
            "id", "conflict_type", "status", "severity", "attribute_name",
            "resolution", "resolution_reason", "created_at", "resolved_at", "evidence",
        }
        assert legacy_fields.issubset(item.keys())
        assert legacy_fields.issubset(detail.keys())
        # The new field is additive and legacy conflicts serialize safely.
        assert item["releases"] == []
        assert detail["releases"] == []
        assert item["evidence"][0]["evidence_id"] == evidence.id
        assert detail["evidence"][0]["evidence_id"] == evidence.id

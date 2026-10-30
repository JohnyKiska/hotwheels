from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.conflict_queue import get_conflict_detail
from app.db import Base
from app.identifier_registration import register_identifier
from app.models import (
    Conflict, ConflictEvidence, ConflictRelease, Evidence, IdentifierType,
    Casting, Release, Source, SourceRecord,
)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed(session):
    session.add(IdentifierType(code="upc", label="UPC"))
    casting = Casting(name="Synthetic casting", status="confirmed")
    session.add(casting)
    session.flush()
    release_a = Release(casting_id=casting.id, catalog_year=2025, name="Synthetic release A", status="confirmed")
    release_b = Release(casting_id=casting.id, catalog_year=2026, name="Synthetic release B", status="candidate")
    session.add_all([release_a, release_b])
    session.flush()
    return release_a, release_b


def source_record(session, name):
    source = Source(name=name, source_type="synthetic_fixture", access_status="available")
    session.add(source)
    session.flush()
    record = SourceRecord(source_id=source.id, record_type="synthetic_identifier_observation")
    session.add(record)
    session.flush()
    return record


def test_identifier_collision_has_release_and_evidence_traceability():
    with make_session() as session:
        release_a, release_b = seed(session)
        source_a = source_record(session, "Synthetic source A")
        source_b = source_record(session, "Synthetic source B")

        register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_a.id, source_record_id=source_a.id,
        )
        result = register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_b.id, source_record_id=source_b.id,
        )
        conflict = result["new_conflicts"][0]

        detail = get_conflict_detail(session, conflict.id)
        assert {item["release_id"] for item in detail["releases"]} == {release_a.id, release_b.id}
        assert {item["release_name"] for item in detail["releases"]} == {
            "Synthetic release A", "Synthetic release B"
        }
        assert len(detail["evidence"]) == 2
        assert {item["source_name"] for item in detail["evidence"]} == {
            "Synthetic source A", "Synthetic source B"
        }
        assert session.scalar(select(func.count()).select_from(ConflictRelease)) == 2
        assert session.scalar(select(func.count()).select_from(ConflictEvidence)) == 2
        assert release_a.status == "confirmed"
        assert release_b.status == "candidate"


def test_existing_collision_is_reconciled_and_retry_is_idempotent_without_evidence():
    with make_session() as session:
        release_a, release_b = seed(session)
        register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_a.id,
        )
        result = register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_b.id,
        )
        conflict = result["new_conflicts"][0]

        assert session.scalar(select(func.count()).select_from(ConflictRelease)) == 2
        assert session.scalar(select(func.count()).select_from(ConflictEvidence)) == 0

        again = register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_b.id,
        )
        detail = get_conflict_detail(session, conflict.id)
        assert again["new_conflicts"] == []
        assert len(detail["releases"]) == 2
        assert detail["evidence"] == []
        assert session.scalar(select(func.count()).select_from(Conflict)) == 1
        assert session.scalar(select(func.count()).select_from(ConflictRelease)) == 2

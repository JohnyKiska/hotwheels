from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.evidence_conflicts import detect_evidence_disagreements
from app.models import (
    Casting,
    Conflict,
    ConflictEvidence,
    Evidence,
    EvidenceRelease,
    Release,
    Source,
    SourceRecord,
)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_entity_and_sources(session):
    casting = Casting(name="Example casting", status="confirmed")
    session.add(casting)
    session.flush()
    release = Release(
        casting_id=casting.id,
        catalog_year=2026,
        name="Example casting",
        status="candidate",
    )
    session.add(release)
    session.flush()

    source = Source(
        name="Catalog source",
        source_type="website",
        access_status="available",
    )
    session.add(source)
    session.flush()
    records = [
        SourceRecord(source_id=source.id, record_type="catalog_entry"),
        SourceRecord(source_id=source.id, record_type="catalog_entry"),
        SourceRecord(source_id=source.id, record_type="catalog_entry"),
    ]
    session.add_all(records)
    session.flush()
    return casting, release, records


def add_claim(session, release, source_record, attribute, value, status="pending"):
    evidence = Evidence(
        source_record_id=source_record.id,
        attribute_name=attribute,
        observed_value=value,
        evidence_type="text",
        assessment="supports",
        review_status=status,
    )
    session.add(evidence)
    session.flush()
    session.add(EvidenceRelease(evidence_id=evidence.id, release_id=release.id))
    session.flush()
    return evidence


def test_different_claims_create_open_conflict_linked_to_both_evidence_rows():
    with make_session() as session:
        _, release, records = seed_entity_and_sources(session)
        first = add_claim(session, release, records[0], "wheel_type", "PR5")
        second = add_claim(session, release, records[1], "wheel_type", "OH5")

        conflicts = detect_evidence_disagreements(
            session, entity_type="release", entity_id=release.id
        )

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.conflict_type == "evidence_disagreement"
        assert conflict.status == "open"
        assert conflict.severity == "medium"
        assert {link.evidence_id for link in conflict.evidence_links} == {
            first.id,
            second.id,
        }
        assert all(link.role == "conflicting_claim" for link in conflict.evidence_links)
        assert first.review_status == second.review_status == "pending"
        assert release.status == "candidate"


def test_repeat_detection_is_idempotent():
    with make_session() as session:
        _, release, records = seed_entity_and_sources(session)
        add_claim(session, release, records[0], "catalog_year", "2026")
        add_claim(session, release, records[1], "catalog_year", "2025")

        first = detect_evidence_disagreements(
            session, entity_type="release", entity_id=release.id
        )
        second = detect_evidence_disagreements(
            session, entity_type="release", entity_id=release.id
        )

        assert len(first) == len(second) == 1
        assert first[0].id == second[0].id
        assert session.scalar(
            select(func.count()).select_from(Conflict).where(
                Conflict.conflict_type == "evidence_disagreement"
            )
        ) == 1
        assert session.scalar(select(func.count()).select_from(ConflictEvidence)) == 2


def test_same_claim_after_whitespace_and_case_normalization_is_not_conflict():
    with make_session() as session:
        _, release, records = seed_entity_and_sources(session)
        add_claim(session, release, records[0], "model_name", "  Twin Mill ")
        add_claim(session, release, records[1], "model_name", "twin   mill")

        conflicts = detect_evidence_disagreements(
            session, entity_type="release", entity_id=release.id
        )
        assert conflicts == []


def test_sku_punctuation_difference_is_preserved_and_flags_conflict():
    with make_session() as session:
        _, release, records = seed_entity_and_sources(session)
        add_claim(session, release, records[0], "identifier:sku", "JHW40-K5N7")
        add_claim(session, release, records[1], "identifier:sku", "JHW40K5N7")

        conflicts = detect_evidence_disagreements(
            session, entity_type="release", entity_id=release.id
        )
        assert len(conflicts) == 1
        assert conflicts[0].severity == "high"
        assert len(conflicts[0].evidence_links) == 2


def test_rejected_and_blank_claims_are_ignored():
    with make_session() as session:
        _, release, records = seed_entity_and_sources(session)
        add_claim(session, release, records[0], "model_name", "Twin Mill")
        add_claim(
            session, release, records[1], "model_name", "Different",
            status="rejected",
        )
        add_claim(session, release, records[2], "model_name", "   ")

        conflicts = detect_evidence_disagreements(
            session, entity_type="release", entity_id=release.id
        )
        assert conflicts == []


def test_only_requested_entity_and_attribute_are_compared():
    with make_session() as session:
        casting, release, records = seed_entity_and_sources(session)
        add_claim(session, release, records[0], "model_name", "Twin Mill")
        add_claim(session, release, records[1], "model_name", "Twin Mill II")
        add_claim(session, release, records[2], "wheel_type", "PR5")

        assert detect_evidence_disagreements(
            session,
            entity_type="release",
            entity_id=release.id,
            attribute_name="wheel_type",
        ) == []
        assert detect_evidence_disagreements(
            session, entity_type="casting", entity_id=casting.id
        ) == []


def test_unsupported_entity_type_is_rejected():
    with make_session() as session:
        try:
            detect_evidence_disagreements(
                session, entity_type="manufacturer", entity_id="unknown"
            )
        except ValueError as exc:
            assert "Unsupported entity_type" in str(exc)
        else:
            raise AssertionError("unsupported entity type should raise ValueError")

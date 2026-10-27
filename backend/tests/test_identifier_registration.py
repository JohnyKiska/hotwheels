from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.db import Base
from app.identifier_registration import register_identifier, UnknownSourceRecord
from app.models import (
    CatalogIdentifier,
    ChangeLog,
    Casting,
    Conflict,
    Evidence,
    EvidenceRelease,
    IdentifierType,
    Release,
    ReleaseIdentifier,
    Source,
    SourceRecord,
)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed(session):
    session.add_all([
        IdentifierType(code="sku", label="SKU"),
        IdentifierType(code="upc", label="UPC"),
    ])
    casting = Casting(name="Example casting", status="confirmed")
    session.add(casting)
    session.flush()
    release_a = Release(
        casting_id=casting.id,
        catalog_year=2025,
        name="Example casting",
        status="confirmed",
    )
    release_b = Release(
        casting_id=casting.id,
        catalog_year=2026,
        name="Example casting",
        status="candidate",
    )
    session.add_all([release_a, release_b])
    session.flush()
    return casting, release_a, release_b


def seed_source_record(session):
    source = Source(
        name="Physical blister photo",
        source_type="physical_reference",
        access_status="available",
    )
    session.add(source)
    session.flush()
    record = SourceRecord(
        source_id=source.id,
        record_type="package_photo",
        raw_data={"filename": "JHW40-front.jpg"},
    )
    session.add(record)
    session.flush()
    return record


def test_register_reuses_normalized_identifier_and_is_idempotent():
    with make_session() as session:
        _, release, _ = seed(session)
        first = register_identifier(
            session,
            type_code="sku",
            value="JHW40-K5N7",
            entity_type="release",
            entity_id=release.id,
            source_note="package photo",
        )
        second = register_identifier(
            session,
            type_code="SKU",
            value=" jhw40-k5n7 ",
            entity_type="release",
            entity_id=release.id,
            source_note="second observation",
        )

        assert first["identifier_created"] is True
        assert first["link_created"] is True
        assert second["identifier_created"] is False
        assert second["link_created"] is False
        assert first["identifier"].id == second["identifier"].id
        assert session.scalar(select(func.count()).select_from(CatalogIdentifier)) == 1
        assert session.scalar(select(func.count()).select_from(ReleaseIdentifier)) == 1
        assert second["link"].source_note == "package photo"
        assert first["evidence"] is None
        assert second["evidence"] is None


def test_source_observation_creates_separate_evidence_linked_to_release():
    with make_session() as session:
        _, release, _ = seed(session)
        source_record = seed_source_record(session)

        result = register_identifier(
            session,
            type_code="sku",
            value="JHW40-K5N7",
            entity_type="release",
            entity_id=release.id,
            source_record_id=source_record.id,
        )

        evidence = result["evidence"]
        assert evidence is not None
        assert evidence.source_record_id == source_record.id
        assert evidence.attribute_name == "identifier:sku"
        assert evidence.observed_value == "JHW40-K5N7"
        assert evidence.review_status == "pending"
        evidence_link = session.get(EvidenceRelease, (evidence.id, release.id))
        assert evidence_link is not None
        assert evidence_link.role == "identifier_observation"
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1


def test_each_source_observation_is_preserved_even_when_identifier_is_reused():
    with make_session() as session:
        _, release, _ = seed(session)
        first_source = seed_source_record(session)
        second_source = seed_source_record(session)

        first = register_identifier(
            session, type_code="sku", value="JHW40-K5N7",
            entity_type="release", entity_id=release.id,
            source_record_id=first_source.id,
        )
        second = register_identifier(
            session, type_code="sku", value="JHW40-K5N7",
            entity_type="release", entity_id=release.id,
            source_record_id=second_source.id,
        )

        assert first["identifier"].id == second["identifier"].id
        assert first["link"].release_id == second["link"].release_id
        assert first["evidence"].id != second["evidence"].id
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2


def test_punctuation_different_skus_remain_separate_identifiers():
    with make_session() as session:
        _, release, _ = seed(session)
        hyphenated = register_identifier(
            session, type_code="sku", value="JHW40-K5N7",
            entity_type="release", entity_id=release.id,
        )
        unhyphenated = register_identifier(
            session, type_code="sku", value="JHW40K5N7",
            entity_type="release", entity_id=release.id,
        )
        assert hyphenated["identifier"].id != unhyphenated["identifier"].id
        assert session.scalar(select(func.count()).select_from(CatalogIdentifier)) == 2


def test_identifier_linked_to_two_releases_creates_one_review_conflict():
    with make_session() as session:
        _, release_a, release_b = seed(session)
        first = register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_a.id,
        )
        second = register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_b.id,
        )

        conflicts = session.scalars(
            select(Conflict).where(Conflict.conflict_type == "identifier_collision")
        ).all()
        assert first["new_conflicts"] == []
        assert second["identifier_created"] is False
        assert second["link_created"] is True
        assert len(second["new_conflicts"]) == 1
        assert len(conflicts) == 1
        assert conflicts[0].status == "open"
        assert conflicts[0].severity == "high"
        assert release_a.status == "confirmed"
        assert release_b.status == "candidate"

        again = register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_b.id,
        )
        assert again["link_created"] is False
        assert again["new_conflicts"] == []
        assert session.scalar(select(func.count()).select_from(Conflict)) == 1



def test_identifier_registration_is_audited_and_noop_retry_does_not_duplicate_event():
    with make_session() as session:
        _, release, _ = seed(session)
        first = register_identifier(
            session,
            type_code="sku",
            value="JHW40-K5N7",
            entity_type="release",
            entity_id=release.id,
            reason="Verified against the front blister photo",
            actor_type="human",
            actor_id="reviewer-1",
        )
        events = session.scalars(
            select(ChangeLog).where(
                ChangeLog.entity_type == "release",
                ChangeLog.entity_id == release.id,
                ChangeLog.action == "register_identifier",
            )
        ).all()
        assert len(events) == 1
        event = events[0]
        assert event.reason == "Verified against the front blister photo"
        assert event.actor_type == "human"
        assert event.actor_id == "reviewer-1"
        assert event.old_values["identifier_exists"] is False
        assert event.old_values["link_exists"] is False
        assert event.new_values["identifier_id"] == first["identifier"].id
        assert event.new_values["identifier_created"] is True
        assert event.new_values["link_created"] is True

        register_identifier(
            session,
            type_code="sku",
            value="JHW40-K5N7",
            entity_type="release",
            entity_id=release.id,
            reason="Retry after import timeout",
        )
        assert session.scalar(
            select(func.count()).select_from(ChangeLog).where(
                ChangeLog.entity_type == "release",
                ChangeLog.entity_id == release.id,
                ChangeLog.action == "register_identifier",
            )
        ) == 1


def test_each_identifier_source_observation_gets_its_own_audit_event():
    with make_session() as session:
        _, release, _ = seed(session)
        first_source = seed_source_record(session)
        second_source = seed_source_record(session)

        first = register_identifier(
            session, type_code="sku", value="JHW40-K5N7",
            entity_type="release", entity_id=release.id,
            source_record_id=first_source.id,
            reason="Read from first package photo",
        )
        second = register_identifier(
            session, type_code="sku", value="JHW40-K5N7",
            entity_type="release", entity_id=release.id,
            source_record_id=second_source.id,
            reason="Confirmed against a second package photo",
        )

        assert first["identifier"].id == second["identifier"].id
        events = session.scalars(
            select(ChangeLog).where(
                ChangeLog.entity_type == "release",
                ChangeLog.entity_id == release.id,
                ChangeLog.action == "register_identifier",
            ).order_by(ChangeLog.created_at, ChangeLog.id)
        ).all()
        assert len(events) == 2
        assert {event.new_values["source_record_id"] for event in events} == {
            first_source.id, second_source.id
        }
        assert {event.new_values["evidence_id"] for event in events} == {
            first["evidence"].id, second["evidence"].id
        }


def test_invalid_actor_type_fails_before_mutating_registration_state():
    with make_session() as session:
        _, release, _ = seed(session)

        try:
            register_identifier(
                session,
                type_code="sku",
                value="JHW40-K5N7",
                entity_type="release",
                entity_id=release.id,
                actor_type="robot",
            )
        except ValueError as exc:
            assert "actor_type" in str(exc)
        else:
            raise AssertionError("invalid actor_type should be rejected")

        assert session.scalar(select(func.count()).select_from(CatalogIdentifier)) == 0
        assert session.scalar(select(func.count()).select_from(ReleaseIdentifier)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeLog)) == 0

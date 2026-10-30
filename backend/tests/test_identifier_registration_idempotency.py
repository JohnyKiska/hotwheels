from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.db import Base
from app.identifier_registration import register_identifier
from app.models import (
    ChangeLog,
    Casting,
    Conflict,
    Evidence,
    EvidenceRelease,
    IdentifierType,
    Release,
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
    casting = Casting(name="Synthetic casting", status="confirmed")
    session.add(casting)
    session.flush()
    releases = [
        Release(casting_id=casting.id, catalog_year=2025, name="Synthetic casting", status="confirmed"),
        Release(casting_id=casting.id, catalog_year=2026, name="Synthetic casting", status="candidate"),
    ]
    session.add_all(releases)
    session.flush()
    return releases


def seed_source_record(session):
    source = Source(
        name="Synthetic fixture source",
        source_type="physical_reference",
        access_status="available",
    )
    session.add(source)
    session.flush()
    record = SourceRecord(
        source_id=source.id,
        record_type="synthetic_test_fixture",
        raw_data={"fixture": True},
    )
    session.add(record)
    session.flush()
    return record


def test_reprocessing_same_source_record_reuses_evidence_and_audit_event():
    with make_session() as session:
        release, _ = seed(session)
        source_record = seed_source_record(session)

        first = register_identifier(
            session, type_code="sku", value="SYNTHETIC-SKU-01",
            entity_type="release", entity_id=release.id,
            source_record_id=source_record.id,
            reason="First importer pass",
        )
        retry = register_identifier(
            session, type_code="SKU", value=" synthetic-sku-01 ",
            entity_type="release", entity_id=release.id,
            source_record_id=source_record.id,
            reason="Retry after timeout",
        )

        assert first["evidence"].id == retry["evidence"].id
        assert first["evidence_created"] is True
        assert retry["evidence_created"] is False
        assert first["evidence_link_created"] is True
        assert retry["evidence_link_created"] is False
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(
            select(func.count()).select_from(ChangeLog).where(
                ChangeLog.entity_type == "release",
                ChangeLog.entity_id == release.id,
                ChangeLog.action == "register_identifier",
            )
        ) == 1


def test_same_source_claim_can_be_linked_to_another_release_without_duplicate_evidence():
    with make_session() as session:
        release_a, release_b = seed(session)
        source_record = seed_source_record(session)

        first = register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_a.id,
            source_record_id=source_record.id,
        )
        second = register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_b.id,
            source_record_id=source_record.id,
        )

        assert first["evidence"].id == second["evidence"].id
        assert second["evidence_created"] is False
        assert second["evidence_link_created"] is True
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.get(EvidenceRelease, (first["evidence"].id, release_a.id)) is not None
        assert session.get(EvidenceRelease, (first["evidence"].id, release_b.id)) is not None
        assert session.scalar(
            select(func.count()).select_from(Conflict).where(
                Conflict.conflict_type == "identifier_collision"
            )
        ) == 1

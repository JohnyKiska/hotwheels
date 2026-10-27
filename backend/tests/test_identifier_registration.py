from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.db import Base
from app.identifier_registration import register_identifier
from app.models import (
    CatalogIdentifier,
    Casting,
    Conflict,
    IdentifierType,
    Release,
    ReleaseIdentifier,
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
        # The first non-empty provenance is not overwritten.
        assert second["link"].source_note == "package photo"


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

        # Running registration again must not create a duplicate link/conflict.
        again = register_identifier(
            session, type_code="upc", value="001234567890",
            entity_type="release", entity_id=release_b.id,
        )
        assert again["link_created"] is False
        assert again["new_conflicts"] == []
        assert session.scalar(select(func.count()).select_from(Conflict)) == 1

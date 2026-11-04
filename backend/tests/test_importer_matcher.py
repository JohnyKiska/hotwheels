from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.db import Base
from app.importers.matcher import match_import_observation
from app.models import (
    Casting,
    CatalogIdentifier,
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


def seed_release(session, *, name="Example casting", year=2025):
    casting = Casting(name=name, status="confirmed")
    session.add(casting)
    session.flush()
    release = Release(
        casting_id=casting.id,
        catalog_year=year,
        name=name,
        status="candidate",
    )
    session.add(release)
    session.flush()
    return casting, release


def observation(*, name=None, year=None, hints=None):
    return {
        "mode": "preview_only",
        "writes_to_catalog": False,
        "subject_hints": {"name": name, "catalog_year": year},
        "claims": [],
        "identifier_hints": hints or [],
    }


def test_exact_name_and_catalog_year_is_a_strong_candidate_without_writes():
    with make_session() as session:
        _, release = seed_release(session)
        before = session.scalar(select(func.count()).select_from(Release))

        result = match_import_observation(
            session, observation(name="Example casting", year=2025)
        )

        assert result["status"] == "strong_candidate"
        assert result["matched_entities"][0]["entity_id"] == release.id
        assert any(s["kind"] == "exact_name_and_catalog_year" for s in result["signals"])
        assert result["writes_to_catalog"] is False
        assert session.scalar(select(func.count()).select_from(Release)) == before
        assert session.scalar(select(func.count()).select_from(CatalogIdentifier)) == 0


def test_identifier_and_matching_catalog_year_produces_strong_candidate():
    with make_session() as session:
        session.add(IdentifierType(code="sku", label="SKU"))
        _, release = seed_release(session)
        identifier_type = session.scalar(
            select(IdentifierType).where(IdentifierType.code == "sku")
        )
        identifier = CatalogIdentifier(
            identifier_type_id=identifier_type.id,
            value="JHW40-K5N7",
            normalized_value="JHW40-K5N7",
        )
        session.add(identifier)
        session.flush()
        session.add(ReleaseIdentifier(release_id=release.id, identifier_id=identifier.id))
        session.flush()

        result = match_import_observation(session, observation(
            name="Different source title",
            year=2025,
            hints=[{"type_code": "sku", "raw_value": "jhw40-k5n7"}],
        ))

        assert result["status"] == "strong_candidate"
        assert result["matched_entities"][0]["entity_id"] == release.id
        assert any(s["kind"] == "release_identifier" for s in result["signals"])


def test_shared_release_identifier_is_reported_as_collision_not_selected():
    with make_session() as session:
        session.add(IdentifierType(code="upc", label="UPC"))
        _, first = seed_release(session, name="First casting", year=2025)
        _, second = seed_release(session, name="Second casting", year=2026)
        identifier_type = session.scalar(
            select(IdentifierType).where(IdentifierType.code == "upc")
        )
        identifier = CatalogIdentifier(
            identifier_type_id=identifier_type.id,
            value="001234567890",
            normalized_value="001234567890",
        )
        session.add(identifier)
        session.flush()
        session.add_all([
            ReleaseIdentifier(release_id=first.id, identifier_id=identifier.id),
            ReleaseIdentifier(release_id=second.id, identifier_id=identifier.id),
        ])
        session.flush()

        result = match_import_observation(session, observation(
            hints=[{"type_code": "upc", "raw_value": "001234567890"}]
        ))

        assert result["status"] == "identifier_collision"
        assert {item["entity_id"] for item in result["matched_entities"]} == {
            first.id, second.id
        }
        assert len(result["contradictions"]) == 1
        assert result["requires_manual_review"] is True


def test_unknown_identifier_namespace_is_explained_and_does_not_match():
    with make_session() as session:
        result = match_import_observation(session, observation(
            hints=[{"type_code": "not_configured", "raw_value": "ABC-123"}]
        ))

        assert result["status"] == "no_match"
        assert result["ignored_identifier_hints"][0]["type_code"] == "not_configured"


def test_exact_source_replay_requires_source_id_and_content_hash():
    with make_session() as session:
        source = Source(
            name="Fixture source",
            source_type="website",
            access_status="available",
        )
        session.add(source)
        session.flush()
        record = SourceRecord(
            source_id=source.id,
            record_type="saved_html",
            content_hash="sha256:fixture",
            raw_data={"fixture": True},
        )
        session.add(record)
        session.flush()

        result = match_import_observation(
            session,
            observation(),
            source_snapshot={
                "source_id": source.id,
                "content_hash": "sha256:fixture",
            },
        )

        assert result["status"] == "exact_source_replay"
        assert result["source_record_id"] == record.id
        assert result["writes_to_catalog"] is False

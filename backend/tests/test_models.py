import pytest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    CatalogIdentifier, Casting, CastingVariant, Evidence, EvidencePackage,
    IdentifierType, Package, PackageIdentifier, PackageRelease, Release, ReleaseSeries,
    Series, Source, SourceRecord,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    # Match the application's SQLite foreign-key enforcement.
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_release_can_have_unknown_year_and_variant(session):
    casting = Casting(name="Test casting")
    release = Release(casting=casting, catalog_year=None, casting_variant=None)
    session.add(release)
    session.commit()

    loaded = session.scalar(select(Release).where(Release.id == release.id))
    assert loaded is not None
    assert loaded.catalog_year is None
    assert loaded.casting_variant_id is None
    assert loaded.status == "candidate"


def test_release_variant_must_belong_to_same_casting(session):
    casting_a = Casting(name="Casting A")
    casting_b = Casting(name="Casting B")
    variant_a = CastingVariant(casting=casting_a, name="Variant A")
    session.add_all([casting_a, casting_b, variant_a])
    session.commit()

    # Direct IDs deliberately bypass any convenience logic in the UI.
    invalid_release = Release(
        casting_id=casting_b.id,
        casting_variant_id=variant_a.id,
        catalog_year=2026,
    )
    session.add(invalid_release)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_release_can_belong_to_multiple_series(session):
    casting = Casting(name="Test casting")
    release = Release(casting=casting, catalog_year=2026)
    series_a = Series(name="Series A")
    series_b = Series(name="Series B")
    session.add_all([release, series_a, series_b])
    session.flush()
    session.add_all([
        ReleaseSeries(release=release, series=series_a),
        ReleaseSeries(release=release, series=series_b),
    ])
    session.commit()

    assert {series.name for series in release.series} == {"Series A", "Series B"}


@pytest.mark.parametrize("bad_year", [1900, 2200])
def test_release_rejects_out_of_range_catalog_year(session, bad_year):
    session.add(Release(casting=Casting(name="Test casting"), catalog_year=bad_year))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_release_rejects_unknown_status(session):
    session.add(Release(casting=Casting(name="Test casting"), status="approved-ish"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_internal_ids_do_not_depend_on_names(session):
    first = Casting(name="Same name")
    second = Casting(name="Same name")
    session.add_all([first, second])
    session.commit()
    assert first.id != second.id



def test_duplicate_release_identity_is_rejected(session):
    casting = Casting(name="Twin Mill")
    session.add_all([
        Release(casting=casting, catalog_year=2026, assortment_number="001"),
        Release(casting=casting, catalog_year=2026, assortment_number="001"),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_same_release_identity_can_differ_by_year(session):
    casting = Casting(name="Twin Mill")
    session.add_all([
        Release(casting=casting, catalog_year=2025, assortment_number="001"),
        Release(casting=casting, catalog_year=2026, assortment_number="001"),
    ])
    session.commit()
    assert session.query(Release).count() == 2


def test_duplicate_release_series_link_is_rejected(session):
    release = Release(casting=Casting(name="Twin Mill"), catalog_year=2026)
    series = Series(name="HW Dream Garage")
    session.add_all([release, series])
    session.flush()
    session.add_all([
        ReleaseSeries(release=release, series=series),
        ReleaseSeries(release=release, series=series),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_series_rejects_unknown_status(session):
    session.add(Series(name="Bad series", status="published"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


@pytest.mark.parametrize("bad_year", [1900, 2200])
def test_casting_rejects_out_of_range_first_known_year(session, bad_year):
    session.add(Casting(name="Invalid year casting", first_known_year=bad_year))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()



def test_deleting_casting_with_release_is_rejected(session):
    casting = Casting(name="Twin Mill")
    release = Release(casting=casting, catalog_year=2026)
    session.add(release)
    session.commit()

    session.delete(casting)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    assert session.get(Casting, casting.id) is not None
    assert session.get(Release, release.id) is not None


def test_deleting_release_removes_its_series_links(session):
    release = Release(casting=Casting(name="Twin Mill"), catalog_year=2026)
    series = Series(name="HW Dream Garage")
    link = ReleaseSeries(release=release, series=series)
    session.add_all([release, series, link])
    session.commit()
    release_id = release.id

    session.delete(release)
    session.commit()

    assert session.get(Release, release_id) is None
    assert session.query(ReleaseSeries).count() == 0
    assert session.query(Series).count() == 1


def test_deleting_series_removes_its_release_links(session):
    release = Release(casting=Casting(name="Twin Mill"), catalog_year=2026)
    series = Series(name="HW Dream Garage")
    link = ReleaseSeries(release=release, series=series)
    session.add_all([release, series, link])
    session.commit()
    series_id = series.id

    session.delete(series)
    session.commit()

    assert session.get(Series, series_id) is None
    assert session.query(ReleaseSeries).count() == 0
    assert session.query(Release).count() == 1



def test_deleting_variant_referenced_by_release_is_rejected(session):
    casting = Casting(name="Twin Mill")
    variant = CastingVariant(casting=casting, name="Different wheels")
    release = Release(casting=casting, casting_variant=variant, catalog_year=2026)
    session.add(release)
    session.commit()
    variant_id = variant.id
    release_id = release.id

    session.delete(variant)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    assert session.get(CastingVariant, variant_id) is not None
    persisted_release = session.get(Release, release_id)
    assert persisted_release is not None
    assert persisted_release.casting_variant_id == variant_id


def test_variant_cannot_be_reassigned_to_different_casting_when_referenced(session):
    casting_a = Casting(name="Casting A")
    casting_b = Casting(name="Casting B")
    variant = CastingVariant(casting=casting_a, name="Variant A")
    release = Release(casting=casting_a, casting_variant=variant, catalog_year=2026)
    session.add_all([casting_b, release])
    session.commit()

    variant.casting = casting_b
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    assert session.get(CastingVariant, variant.id).casting_id == casting_a.id
    assert session.get(Release, release.id).casting_id == casting_a.id

def test_release_cannot_be_reassigned_to_casting_that_does_not_own_its_variant(session):
    casting_a = Casting(name="Casting A")
    casting_b = Casting(name="Casting B")
    variant_a = CastingVariant(casting=casting_a, name="Variant A")
    release = Release(casting=casting_a, casting_variant=variant_a, catalog_year=2026)
    session.add_all([casting_b, release])
    session.commit()

    release.casting = casting_b
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    persisted_release = session.get(Release, release.id)
    assert persisted_release is not None
    assert persisted_release.casting_id == casting_a.id
    assert persisted_release.casting_variant_id == variant_a.id


def test_release_cannot_switch_to_variant_owned_by_another_casting(session):
    casting_a = Casting(name="Casting A")
    casting_b = Casting(name="Casting B")
    variant_a = CastingVariant(casting=casting_a, name="Variant A")
    variant_b = CastingVariant(casting=casting_b, name="Variant B")
    release = Release(casting=casting_a, casting_variant=variant_a, catalog_year=2026)
    session.add_all([casting_b, release, variant_b])
    session.commit()

    release.casting_variant = variant_b
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    persisted_release = session.get(Release, release.id)
    assert persisted_release is not None
    assert persisted_release.casting_id == casting_a.id
    assert persisted_release.casting_variant_id == variant_a.id

def test_database_restricts_direct_delete_of_referenced_variant(session):
    casting = Casting(name="Twin Mill")
    variant = CastingVariant(casting=casting, name="Different wheels")
    release = Release(casting=casting, casting_variant=variant, catalog_year=2026)
    session.add(release)
    session.commit()

    # Bypass ORM relationship handling to verify the SQLite foreign key itself.
    with pytest.raises(IntegrityError):
        session.execute(
            delete(CastingVariant).where(CastingVariant.id == variant.id)
        )
        session.commit()
    session.rollback()

    assert session.get(CastingVariant, variant.id) is not None
    assert session.get(Release, release.id).casting_variant_id == variant.id


def test_database_restricts_direct_reassignment_of_referenced_variant(session):
    casting_a = Casting(name="Casting A")
    casting_b = Casting(name="Casting B")
    variant = CastingVariant(casting=casting_a, name="Variant A")
    release = Release(casting=casting_a, casting_variant=variant, catalog_year=2026)
    session.add_all([casting_b, release])
    session.commit()

    # Bypass ORM relationship synchronization and test the composite FK directly.
    with pytest.raises(IntegrityError):
        session.execute(
            update(CastingVariant)
            .where(CastingVariant.id == variant.id)
            .values(casting_id=casting_b.id)
        )
        session.commit()
    session.rollback()

    assert session.get(CastingVariant, variant.id).casting_id == casting_a.id
    persisted_release = session.get(Release, release.id)
    assert persisted_release.casting_id == casting_a.id
    assert persisted_release.casting_variant_id == variant.id




def test_deleting_casting_removes_unreferenced_variants(session):
    casting = Casting(name="Twin Mill")
    variants = [
        CastingVariant(casting=casting, name="Variant A"),
        CastingVariant(casting=casting, name="Variant B"),
    ]
    session.add(casting)
    session.commit()
    casting_id = casting.id
    variant_ids = [variant.id for variant in variants]

    session.delete(casting)
    session.commit()

    assert session.get(Casting, casting_id) is None
    assert all(session.get(CastingVariant, variant_id) is None for variant_id in variant_ids)


def test_deleting_casting_with_multiple_variants_is_blocked_if_one_is_referenced(session):
    casting = Casting(name="Twin Mill")
    referenced_variant = CastingVariant(casting=casting, name="Real Riders")
    unreferenced_variant = CastingVariant(casting=casting, name="Basic wheels")
    release = Release(
        casting=casting,
        casting_variant=referenced_variant,
        catalog_year=2026,
    )
    session.add(release)
    session.commit()
    casting_id = casting.id
    referenced_variant_id = referenced_variant.id
    unreferenced_variant_id = unreferenced_variant.id
    release_id = release.id

    session.delete(casting)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    assert session.get(Casting, casting_id) is not None
    assert session.get(CastingVariant, referenced_variant_id) is not None
    assert session.get(CastingVariant, unreferenced_variant_id) is not None
    persisted_release = session.get(Release, release_id)
    assert persisted_release is not None
    assert persisted_release.casting_id == casting_id
    assert persisted_release.casting_variant_id == referenced_variant_id


def test_database_restricts_direct_delete_of_casting_with_variants(session):
    casting = Casting(name="Twin Mill")
    variant = CastingVariant(casting=casting, name="Real Riders")
    session.add(variant)
    session.commit()
    casting_id = casting.id
    variant_id = variant.id

    # Raw SQLAlchemy Core DELETE bypasses the ORM's configured child cascade.
    with pytest.raises(IntegrityError):
        session.execute(delete(Casting).where(Casting.id == casting_id))
        session.commit()
    session.rollback()

    assert session.get(Casting, casting_id) is not None
    assert session.get(CastingVariant, variant_id) is not None


def test_evidence_can_link_to_multiple_entity_types_once(session):
    from app.models import Evidence, EvidenceCasting, EvidenceRelease, Source, SourceRecord

    source = Source(name="Official catalog", source_type="catalog", is_official=True)
    record = SourceRecord(source=source, record_type="catalog_entry", raw_data={"year": 2026})
    evidence = Evidence(source_record=record, attribute_name="catalog_year", observed_value="2026")
    casting = Casting(name="Twin Mill")
    release = Release(casting=casting, catalog_year=2026)
    session.add_all([evidence, casting, release])
    session.flush()
    evidence.casting_links.append(EvidenceCasting(casting=casting))
    evidence.release_links.append(EvidenceRelease(release=release))
    session.commit()

    loaded = session.get(Evidence, evidence.id)
    assert loaded.source_record.source.name == "Official catalog"
    assert len(loaded.casting_links) == 1
    assert len(loaded.release_links) == 1
    assert loaded.source_record.raw_data == {"year": 2026}


def test_media_metadata_is_stored_without_media_bytes(session):
    from app.models import MediaAsset, Source, SourceRecord

    record = SourceRecord(source=Source(name="Physical blister", source_type="photo"), record_type="photo")
    asset = MediaAsset(source_record=record, storage_key="evidence/sha256/abc.webp",
                       checksum_sha256="a" * 64, mime_type="image/webp")
    session.add(asset)
    session.commit()
    loaded = session.get(MediaAsset, asset.id)
    assert loaded.storage_key == "evidence/sha256/abc.webp"
    assert loaded.checksum_sha256 == "a" * 64


def test_conflict_and_change_log_can_reference_same_evidence(session):
    from app.models import ChangeLog, ChangeLogEvidence, Conflict, ConflictEvidence, Evidence, Source, SourceRecord

    evidence = Evidence(source_record=SourceRecord(
        source=Source(name="Catalog", source_type="web"), record_type="entry"
    ), attribute_name="wheel_type", observed_value="5-spoke")
    conflict = Conflict(conflict_type="wheel_type_disagreement", attribute_name="wheel_type")
    change = ChangeLog(entity_type="release", entity_id="release-id", action="updated",
                      old_values={"wheel_type": "5-spoke"}, new_values={"wheel_type": "pr5"},
                      reason="Manual verification")
    session.add_all([evidence, conflict, change])
    session.flush()
    conflict.evidence_links.append(ConflictEvidence(evidence=evidence, role="contradicts"))
    change.evidence_links.append(ChangeLogEvidence(evidence=evidence))
    session.commit()

    assert session.query(ConflictEvidence).count() == 1
    assert session.query(ChangeLogEvidence).count() == 1
    assert session.get(ChangeLog, change.id).reason == "Manual verification"


def test_evidence_rejects_invalid_assessment(session):
    from app.models import Evidence, Source, SourceRecord
    session.add(Evidence(source_record=SourceRecord(
        source=Source(name="Catalog", source_type="web"), record_type="entry"
    ), attribute_name="sku", assessment="guess"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_duplicate_evidence_entity_link_is_rejected(session):
    from app.models import Evidence, EvidenceCasting, Source, SourceRecord
    evidence = Evidence(source_record=SourceRecord(
        source=Source(name="Catalog", source_type="web"), record_type="entry"
    ), attribute_name="name", observed_value="Twin Mill")
    casting = Casting(name="Twin Mill")
    session.add_all([evidence, casting])
    session.flush()
    session.add_all([EvidenceCasting(evidence=evidence, casting=casting),
                     EvidenceCasting(evidence=evidence, casting=casting)])
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()



def test_source_snapshot_and_evidence_are_not_cascade_deleted(session):
    from app.models import Evidence, Source, SourceRecord

    source = Source(name="Catalog source", source_type="web")
    record = SourceRecord(source=source, record_type="catalog_entry", raw_data={"sku": "ABC"})
    evidence = Evidence(source_record=record, attribute_name="sku", observed_value="ABC")
    session.add(evidence)
    session.commit()

    session.delete(source)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    assert session.get(Source, source.id) is not None
    assert session.get(SourceRecord, record.id) is not None
    assert session.get(Evidence, evidence.id) is not None


def test_source_record_with_evidence_cannot_be_deleted(session):
    from app.models import Evidence, Source, SourceRecord

    record = SourceRecord(
        source=Source(name="Catalog source", source_type="web"),
        record_type="catalog_entry",
        raw_data={"sku": "ABC"},
    )
    evidence = Evidence(source_record=record, attribute_name="sku", observed_value="ABC")
    session.add(evidence)
    session.commit()

    session.delete(record)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    assert session.get(SourceRecord, record.id) is not None
    assert session.get(Evidence, evidence.id) is not None


def test_alembic_upgrade_is_safe_on_initialized_existing_database(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import Session

    from app import models  # noqa: F401
    from app.db import Base

    database_path = tmp_path / "existing.db"
    url = f"sqlite:///{database_path}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        casting = Casting(name="Existing record must survive")
        db.add(casting)
        db.commit()
        casting_id = casting.id
    engine.dispose()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(config, "head")
    # A second upgrade to head must be a no-op: no duplicate version rows,
    # no loss of pre-existing records, and no migration error.
    command.upgrade(config, "head")

    check_engine = create_engine(url)
    try:
        inspector = inspect(check_engine)
        tables = set(inspector.get_table_names())
        assert "alembic_version" in tables
        assert "sources" in tables
        assert "evidence" in tables
        assert "packages" in tables
        assert "package_releases" in tables
        assert "package_identifiers" in tables
        assert "evidence_packages" in tables
        with check_engine.connect() as connection:
            assert connection.execute(
                text("SELECT name FROM castings WHERE id = :id"), {"id": casting_id}
            ).scalar_one() == "Existing record must survive"
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261029_origin_reference"
            assert connection.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one() == 1
    finally:
        check_engine.dispose()



def test_database_rejects_orphan_source_record_and_evidence(session):
    from app.models import Evidence, SourceRecord

    orphan_record = SourceRecord(source_id="missing-source", record_type="catalog_entry")
    session.add(orphan_record)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    orphan_evidence = Evidence(
        source_record_id="missing-record",
        attribute_name="catalog_year",
        observed_value="2026",
    )
    session.add(orphan_evidence)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_source_and_source_record_cannot_be_deleted_while_audit_evidence_depends_on_them(session):
    from app.models import Evidence, Source, SourceRecord

    source = Source(name="Official catalog", source_type="catalog")
    record = SourceRecord(source=source, record_type="catalog_entry")
    evidence = Evidence(
        source_record=record,
        attribute_name="catalog_year",
        observed_value="2026",
    )
    session.add(evidence)
    session.commit()
    source_id, record_id, evidence_id = source.id, record.id, evidence.id

    # Audit history must remain intact; database RESTRICT constraints, not only
    # ORM behavior, must prevent deleting the source or its captured record.
    with pytest.raises(IntegrityError):
        session.delete(source)
        session.commit()
    session.rollback()

    with pytest.raises(IntegrityError):
        session.execute(delete(SourceRecord).where(SourceRecord.id == record_id))
        session.commit()
    session.rollback()

    assert session.get(Source, source_id) is not None
    assert session.get(SourceRecord, record_id) is not None
    assert session.get(Evidence, evidence_id) is not None



def test_catalog_relationships_round_trip_with_evidence_and_multiple_series(session):
    from app.models import (
        Evidence,
        EvidenceCasting,
        EvidenceCastingVariant,
        EvidenceRelease,
        EvidenceSeries,
        Source,
        SourceRecord,
    )

    casting = Casting(name="Twin Mill", status="confirmed")
    variant = CastingVariant(casting=casting, name="Real Riders", status="confirmed")
    release = Release(
        casting=casting,
        casting_variant=variant,
        catalog_year=2026,
        assortment_number="001",
        status="confirmed",
    )
    series_a = Series(name="Car Culture", series_type="collection", status="confirmed")
    series_b = Series(name="Japan Historics", series_type="series", status="confirmed")
    release.series_links.extend([
        ReleaseSeries(series=series_a, relation_note="collection membership"),
        ReleaseSeries(series=series_b, relation_note="series membership"),
    ])
    evidence = Evidence(
        source_record=SourceRecord(
            source=Source(name="Official catalog", source_type="catalog", is_official=True),
            record_type="catalog_entry",
            raw_data={"name": "Twin Mill", "year": 2026, "number": "001"},
        ),
        attribute_name="catalog_entry",
        observed_value="Twin Mill / 2026 / 001",
        review_status="manually_verified",
    )
    session.add_all([release, evidence])
    session.flush()
    evidence.casting_links.append(EvidenceCasting(casting=casting))
    evidence.variant_links.append(EvidenceCastingVariant(casting_variant=variant))
    evidence.release_links.append(EvidenceRelease(release=release))
    evidence.series_links.extend([
        EvidenceSeries(series=series_a),
        EvidenceSeries(series=series_b),
    ])
    session.commit()

    # Reload all objects from the database to verify persisted relationships,
    # not just the in-memory object graph assembled by the ORM.
    session.expire_all()
    loaded_release = session.get(Release, release.id)
    loaded_evidence = session.get(Evidence, evidence.id)

    assert loaded_release is not None
    assert loaded_release.casting.name == "Twin Mill"
    assert loaded_release.casting_variant.name == "Real Riders"
    assert {series.name for series in loaded_release.series} == {"Car Culture", "Japan Historics"}
    assert {link.relation_note for link in loaded_release.series_links} == {
        "collection membership", "series membership"
    }
    assert loaded_evidence is not None
    assert loaded_evidence.source_record.raw_data["number"] == "001"
    assert {link.casting.name for link in loaded_evidence.casting_links} == {"Twin Mill"}
    assert {link.casting_variant.name for link in loaded_evidence.variant_links} == {"Real Riders"}
    assert {link.release.assortment_number for link in loaded_evidence.release_links} == {"001"}
    assert {link.series.name for link in loaded_evidence.series_links} == {
        "Car Culture", "Japan Historics"
    }



def test_media_assets_require_unique_storage_keys_and_protect_source_snapshots(session):
    from app.models import MediaAsset, Source, SourceRecord

    record = SourceRecord(
        source=Source(name="Physical blister photo", source_type="physical_reference"),
        record_type="photo_reference",
        raw_data={"item_number": "JHW40", "visible_number": 149},
    )
    first_asset = MediaAsset(
        source_record=record,
        storage_key="hotwheels/reference/JHW40-front.webp",
        original_filename="JHW40.webp",
        mime_type="image/webp",
        checksum_sha256="a" * 64,
    )
    session.add(first_asset)
    session.commit()
    record_id, asset_id = record.id, first_asset.id

    # Storage keys identify one stored object and must not be reused.
    session.add(MediaAsset(
        source_record=record,
        storage_key="hotwheels/reference/JHW40-front.webp",
        original_filename="duplicate.webp",
        mime_type="image/webp",
        checksum_sha256="b" * 64,
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # The source snapshot cannot be deleted while its media evidence exists.
    with pytest.raises(IntegrityError):
        session.execute(delete(SourceRecord).where(SourceRecord.id == record_id))
        session.commit()
    session.rollback()

    assert session.get(SourceRecord, record_id) is not None
    assert session.get(MediaAsset, asset_id) is not None


def test_same_identifier_can_be_assigned_to_two_releases_for_manual_review(session):
    from app.models import CatalogIdentifier, IdentifierType, ReleaseIdentifier

    casting_a = Casting(name="Twin Mill")
    casting_b = Casting(name="Twin Mill variant candidate")
    release_a = Release(casting=casting_a, catalog_year=2025)
    release_b = Release(casting=casting_b, catalog_year=2026)
    identifier_type = IdentifierType(code="sku", label="SKU")
    identifier = CatalogIdentifier(
        identifier_type=identifier_type,
        value="ABC-123",
        normalized_value="ABC-123",
    )
    session.add_all([release_a, release_b, identifier])
    session.flush()
    session.add_all([
        ReleaseIdentifier(release=release_a, identifier=identifier),
        ReleaseIdentifier(release=release_b, identifier=identifier),
    ])
    session.commit()

    assert session.query(ReleaseIdentifier).filter_by(identifier_id=identifier.id).count() == 2
    # A shared SKU is captured faithfully; it does not merge or confirm either release.


def test_identifier_value_is_unique_only_inside_its_type(session):
    from app.models import CatalogIdentifier, IdentifierType

    sku = IdentifierType(code="sku", label="SKU")
    upc = IdentifierType(code="upc", label="UPC")
    session.add_all([
        CatalogIdentifier(identifier_type=sku, value="123", normalized_value="123"),
        CatalogIdentifier(identifier_type=upc, value="123", normalized_value="123"),
    ])
    session.commit()
    assert session.query(CatalogIdentifier).count() == 2


def test_duplicate_normalized_identifier_in_same_namespace_is_rejected(session):
    from app.models import CatalogIdentifier, IdentifierType

    identifier_type = IdentifierType(code="sku", label="SKU")
    session.add_all([
        CatalogIdentifier(identifier_type=identifier_type, value="abc-123", normalized_value="ABC-123"),
        CatalogIdentifier(identifier_type=identifier_type, value="ABC-123", normalized_value="ABC-123"),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_shared_identifier_creates_review_conflict_once(session):
    from app.identifier_conflicts import create_identifier_collision_conflicts
    from app.models import CatalogIdentifier, IdentifierType, ReleaseIdentifier, Conflict

    identifier_type = IdentifierType(code="sku", label="SKU")
    identifier = CatalogIdentifier(
        identifier_type=identifier_type, value="SKU-77", normalized_value="SKU-77"
    )
    release_a = Release(casting=Casting(name="Car A"), catalog_year=2025)
    release_b = Release(casting=Casting(name="Car B"), catalog_year=2026)
    session.add_all([identifier, release_a, release_b])
    session.flush()
    session.add_all([
        ReleaseIdentifier(release=release_a, identifier=identifier),
        ReleaseIdentifier(release=release_b, identifier=identifier),
    ])
    session.flush()

    created = create_identifier_collision_conflicts(session)
    assert len(created) == 1
    assert created[0].conflict_type == "identifier_collision"
    assert created[0].attribute_name == "sku:SKU-77"
    assert created[0].status == "open"

    assert create_identifier_collision_conflicts(session) == []
    assert session.query(Conflict).filter_by(conflict_type="identifier_collision").count() == 1
    session.commit()



def test_change_log_is_append_only_after_migrations(tmp_path, monkeypatch):
    """SQLite must reject edits/deletes while allowing new audit entries."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import DBAPIError

    database_path = tmp_path / "append_only.db"
    url = f"sqlite:///{database_path}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO change_log
                        (id, entity_type, entity_id, action, reason, actor_type, created_at)
                    VALUES
                        ('audit-test-1', 'release', 'release-test-1', 'created',
                         'Initial audit event', 'test', CURRENT_TIMESTAMP)
                """)
            )

        with pytest.raises(DBAPIError, match="append-only"):
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE change_log SET reason = 'rewritten' WHERE id = 'audit-test-1'")
                )

        with pytest.raises(DBAPIError, match="cannot be deleted"):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM change_log WHERE id = 'audit-test-1'")
                )

        # Failed mutation attempts must not damage the original historical fact.
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT reason FROM change_log WHERE id = 'audit-test-1'")
            ).scalar_one()
            assert row == "Initial audit event"

        # A later correction is represented by a new row, not an update.
        with engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO change_log
                        (id, entity_type, entity_id, action, reason, actor_type, created_at)
                    VALUES
                        ('audit-test-2', 'release', 'release-test-1', 'corrected',
                         'Correction recorded as a new event', 'test', CURRENT_TIMESTAMP)
                """)
            )
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM change_log WHERE entity_id = 'release-test-1'")
            ).scalar_one() == 2
    finally:
        engine.dispose()



def test_package_preserves_ordered_contents_and_does_not_merge_release_identity(session):
    casting = Casting(name="Package test casting")
    first = Release(casting=casting, catalog_year=2026, name="First car")
    second = Release(casting=casting, catalog_year=2026, name="Second car")
    package = Package(name="Test 2-pack", package_type="multi_pack", declared_quantity=2)
    session.add_all([first, second, package])
    session.flush()
    session.add_all([
        PackageRelease(package=package, position=2, release=second),
        PackageRelease(package=package, position=1, release=first),
    ])
    session.commit()

    loaded = session.get(Package, package.id)
    assert loaded is not None
    assert [(link.position, link.release.name) for link in loaded.release_links] == [
        (1, "First car"),
        (2, "Second car"),
    ]
    assert session.get(Release, first.id) is not None
    assert session.get(Release, second.id) is not None


def test_package_contents_reject_duplicate_positions(session):
    release_a = Release(casting=Casting(name="Casting A"), catalog_year=2026)
    release_b = Release(casting=Casting(name="Casting B"), catalog_year=2026)
    package = Package(name="Test package")
    session.add_all([release_a, release_b, package])
    session.flush()
    session.add_all([
        PackageRelease(package=package, position=1, release=release_a),
        PackageRelease(package=package, position=1, release=release_b),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_package_identifier_and_evidence_are_linked_to_package(session):
    package = Package(name="Test blister")
    identifier_type = IdentifierType(
        code="package_test_number", label="Package test number"
    )
    identifier = CatalogIdentifier(
        identifier_type=identifier_type,
        value="JHW-TEST-PACK",
        normalized_value="JHW-TEST-PACK",
    )
    source = Source(name="Physical package", source_type="physical_reference")
    source_record = SourceRecord(
        source=source,
        record_type="package",
        raw_data={"package_number": "JHW-TEST-PACK"},
    )
    evidence = Evidence(
        source_record=source_record,
        attribute_name="package_number",
        observed_value="JHW-TEST-PACK",
    )
    session.add_all([package, identifier, evidence])
    session.flush()
    session.add(PackageIdentifier(package=package, identifier=identifier))
    session.add(EvidencePackage(evidence=evidence, package=package, role="supports"))
    session.commit()

    loaded = session.get(Package, package.id)
    assert loaded is not None
    assert len(loaded.identifier_links) == 1
    assert loaded.identifier_links[0].identifier.value == "JHW-TEST-PACK"
    assert len(loaded.evidence_links) == 1
    assert loaded.evidence_links[0].evidence.observed_value == "JHW-TEST-PACK"


def test_deleting_package_removes_links_but_preserves_release(session):
    release = Release(casting=Casting(name="Included car"), catalog_year=2026)
    package = Package(name="Test pack")
    session.add_all([release, package])
    session.flush()
    session.add(PackageRelease(package=package, position=1, release=release))
    session.commit()
    package_id, release_id = package.id, release.id

    session.delete(package)
    session.commit()

    assert session.get(Package, package_id) is None
    assert session.query(PackageRelease).count() == 0
    assert session.get(Release, release_id) is not None


def test_release_cannot_be_deleted_while_referenced_by_package(session):
    release = Release(casting=Casting(name="Included car"), catalog_year=2026)
    package = Package(name="Test pack")
    session.add_all([release, package])
    session.flush()
    session.add(PackageRelease(package=package, position=1, release=release))
    session.commit()
    release_id = release.id

    session.delete(release)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    assert session.get(Release, release_id) is not None

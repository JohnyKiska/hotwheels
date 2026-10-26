import pytest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Casting, CastingVariant, Release, ReleaseSeries, Series


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

    check_engine = create_engine(url)
    try:
        inspector = inspect(check_engine)
        tables = set(inspector.get_table_names())
        assert "alembic_version" in tables
        assert "sources" in tables
        assert "evidence" in tables
        with check_engine.connect() as connection:
            assert connection.execute(
                text("SELECT name FROM castings WHERE id = :id"), {"id": casting_id}
            ).scalar_one() == "Existing record must survive"
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261026_evidence_layer"
    finally:
        check_engine.dispose()

import pytest
from sqlalchemy import create_engine, select
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


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

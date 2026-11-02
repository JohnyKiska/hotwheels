from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.mainline_importer import import_mainline_snapshot
from app.models import (
    CatalogIdentifier,
    CatalogNode,
    Casting,
    Evidence,
    EvidenceRelease,
    IdentifierType,
    Release,
    ReleaseIdentifier,
    Series,
    SourceRecord,
)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine, Session(engine)


def snapshot(rows):
    return {
        "year": 2024,
        "source": {"url": "https://hotwheels.fandom.com/wiki/List_of_2024_Hot_Wheels"},
        "records": rows,
    }


def row(sku, model_name, source_row, series="Factory Fresh", series_number="5/10"):
    return {
        "toy_number": sku,
        "collector_number": "047",
        "model_name": model_name,
        "series_name": series,
        "series_number_raw": series_number,
        "source_annotations": {"model": [], "series": []},
        "source_row": source_row,
    }


def test_import_creates_candidate_releases_with_source_evidence_and_tree():
    engine, session = make_session()
    try:
        result = import_mainline_snapshot(
            session,
            snapshot([
                row("HTC50", "'72 Stingray Convertible", 47),
                row("HTD01", "Ford F-150 Lightning Custom (2nd Color)", 37, "HW Green Speed"),
            ]),
        )
        session.commit()

        assert result["stats"]["releases_created"] == 2
        releases = list(session.scalars(select(Release).order_by(Release.name)))
        assert len(releases) == 2
        assert all(release.status == "candidate" for release in releases)
        assert all(release.casting.first_known_year is None for release in releases)
        assert len(list(session.scalars(select(Casting)))) == 2
        assert len(list(session.scalars(select(Series)))) == 2
        assert len(list(session.scalars(select(SourceRecord)))) == 2
        assert len(list(session.scalars(select(Evidence)))) >= 8
        assert len(list(session.scalars(select(EvidenceRelease)))) >= 8
        assert session.scalar(select(CatalogNode).where(CatalogNode.node_type == "root")) is not None
        assert session.scalar(select(CatalogNode).where(CatalogNode.node_type == "release")) is not None
        assert all(e.review_status == "pending" for e in session.scalars(select(Evidence)))
    finally:
        session.close()
        engine.dispose()


def test_color_annotations_keep_distinct_releases_but_share_candidate_casting():
    engine, session = make_session()
    try:
        result = import_mainline_snapshot(
            session,
            snapshot([
                row("AAA01", "Twin Mill", 1),
                row("AAA02", "Twin Mill (2nd Color)", 2),
            ]),
        )
        session.commit()

        assert result["stats"]["releases_created"] == 2
        assert session.query(Casting).count() == 1
        assert session.query(Release).count() == 2
        assert {release.name for release in session.scalars(select(Release))} == {
            "Twin Mill", "Twin Mill (2nd Color)"
        }
    finally:
        session.close()
        engine.dispose()


def test_distinct_collector_numbers_are_structured_release_identifiers():
    engine, session = make_session()
    try:
        first = row("HTC65", "Nissan Skyline 2000GT-R LBWK", 191, "Then and Now")
        first["collector_number"] = "191"
        second = row("HRY85", "Nissan Skyline 2000GT-R LBWK", 213, "Tooned")
        second["collector_number"] = "213"

        result = import_mainline_snapshot(session, snapshot([first, second]))
        session.commit()

        assert result["stats"]["releases_created"] == 2
        releases = list(session.scalars(select(Release)))
        assert len(releases) == 2
        # Matching model names may share a candidate Casting, but not a Release.
        assert len({release.id for release in releases}) == 2

        catalog_number_type = session.scalar(
            select(IdentifierType).where(IdentifierType.code == "catalog_number")
        )
        assert catalog_number_type is not None
        identifiers = list(session.scalars(
            select(CatalogIdentifier).where(
                CatalogIdentifier.identifier_type_id == catalog_number_type.id
            )
        ))
        assert {identifier.value for identifier in identifiers} == {"191", "213"}

        links = list(session.scalars(
            select(ReleaseIdentifier)
            .join(CatalogIdentifier, CatalogIdentifier.id == ReleaseIdentifier.identifier_id)
            .where(CatalogIdentifier.identifier_type_id == catalog_number_type.id)
        ))
        assert len(links) == 2
        assert {link.role for link in links} == {"secondary"}
        assert len({link.release_id for link in links}) == 2
        assert result["stats"]["catalog_number_identifiers_created"] == 2
        assert result["stats"]["release_catalog_number_links_created"] == 2
    finally:
        session.close()
        engine.dispose()


def test_reimport_of_identical_snapshot_is_idempotent():
    engine, session = make_session()
    try:
        data = snapshot([row("HTC50", "'72 Stingray Convertible", 47)])
        first = import_mainline_snapshot(session, data)
        session.commit()
        second = import_mainline_snapshot(session, data)
        session.commit()

        assert first["stats"]["releases_created"] == 1
        assert second["stats"]["rows_unchanged_skipped"] == 1
        assert session.query(Release).count() == 1
        assert session.query(SourceRecord).count() == 1
        # Each Release has a primary SKU and a secondary collector-number link.
        assert session.query(ReleaseIdentifier).count() == 2
        assert session.query(CatalogIdentifier).count() == 2
    finally:
        session.close()
        engine.dispose()


def test_duplicate_sku_is_reported_not_used_to_merge_rows():
    engine, session = make_session()
    try:
        result = import_mainline_snapshot(
            session,
            snapshot([
                row("AAA01", "Twin Mill", 1),
                row("AAA01", "Twin Mill (2nd Color)", 2),
            ]),
        )
        session.commit()

        assert result["duplicate_skus"] == ["AAA01"]
        assert session.query(Release).count() == 2
        # The duplicate SKU remains linked to both distinct Releases; each
        # Release also has its collector-number link.
        assert session.query(ReleaseIdentifier).count() == 4
        assert session.query(Release).count() == 2
    finally:
        session.close()
        engine.dispose()

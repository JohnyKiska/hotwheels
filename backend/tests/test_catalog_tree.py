import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    Brand,
    CatalogNode,
    Casting,
    ChangeLog,
    Package,
    ProductLine,
    ProductLineBrand,
    Release,
    Series,
)
from app.catalog_tree import move_catalog_node


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
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


def test_product_line_is_distinct_from_series_and_can_link_brands(session):
    brand = Brand(name="Hot Wheels")
    line = ProductLine(name="Hot Wheels Premium", line_type="premium")
    line.brand_links.append(ProductLineBrand(brand=brand, role="primary"))
    session.add(line)
    session.commit()

    loaded = session.scalar(select(ProductLine).where(ProductLine.id == line.id))
    assert loaded is not None
    assert loaded.line_type == "premium"
    assert loaded.brand_links[0].brand.name == "Hot Wheels"
    assert loaded.id != loaded.brand_links[0].brand.id


def test_catalog_node_typed_foreign_key_round_trips(session):
    line = ProductLine(name="Mainline", line_type="mainline")
    root = CatalogNode(node_type="root", label_override="Catalog")
    session.add_all([line, root])
    session.flush()
    line_node = CatalogNode(
        parent=root,
        node_type="product_line",
        product_line=line,
        sort_order=1,
    )
    year_node = CatalogNode(parent=line_node, node_type="year", catalog_year=2026)
    casting = Casting(name="Skyline")
    release = Release(casting=casting, catalog_year=2026)
    session.add(release)
    session.flush()
    release_node = CatalogNode(parent=year_node, node_type="release", release=release)
    session.add_all([line_node, year_node, release_node])
    session.commit()

    session.expire_all()
    loaded = session.get(CatalogNode, release_node.id)
    assert loaded is not None
    assert loaded.release.name is None
    assert loaded.parent.node_type == "year"
    assert loaded.parent.catalog_year == 2026
    assert loaded.parent.parent.product_line.name == "Mainline"


@pytest.mark.parametrize(
    "node_type,fields",
    [
        ("product_line", {"series_id": "not-a-real-series"}),
        ("release", {"release_id": None}),
        ("year", {"catalog_year": None}),
        ("root", {"catalog_year": 2026}),
    ],
)
def test_catalog_node_rejects_mismatched_type_and_reference(session, node_type, fields):
    node = CatalogNode(node_type=node_type, **fields)
    session.add(node)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_catalog_node_can_place_one_release_in_multiple_branches_without_duplication(session):
    casting = Casting(name="Skyline")
    release = Release(casting=casting, catalog_year=2026)
    root = CatalogNode(node_type="root")
    group_a = CatalogNode(node_type="group", parent=root, label_override="J-Imports")
    group_b = CatalogNode(node_type="group", parent=root, label_override="Nissan")
    session.add_all([release, root, group_a, group_b])
    session.flush()
    node_a = CatalogNode(node_type="release", parent=group_a, release=release)
    node_b = CatalogNode(node_type="release", parent=group_b, release=release)
    session.add_all([node_a, node_b])
    session.commit()

    assert session.query(Release).count() == 1
    assert session.query(CatalogNode).filter_by(release_id=release.id).count() == 2


def test_catalog_node_rejects_orphan_foreign_keys_and_protects_referenced_entities(session):
    line = ProductLine(name="Premium", line_type="premium")
    session.add(line)
    session.commit()

    node = CatalogNode(node_type="product_line", product_line_id=line.id)
    session.add(node)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    root = CatalogNode(node_type="root")
    node = CatalogNode(node_type="product_line", parent=root, product_line=line)
    session.add_all([root, node])
    session.commit()
    session.delete(line)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_catalog_tree_move_prevents_cycles_and_invalid_parent_types_and_audits(session):
    root = CatalogNode(node_type="root")
    line = ProductLine(name="Mainline", line_type="mainline")
    line_node = CatalogNode(node_type="product_line", product_line=line, parent=root)
    year = CatalogNode(node_type="year", catalog_year=2026, parent=line_node)
    group = CatalogNode(node_type="group", parent=year)
    session.add_all([root, line_node, year, group])
    session.commit()

    with pytest.raises(ValueError, match="cycle"):
        move_catalog_node(session, line_node.id, group.id, reason="bad move")
    with pytest.raises(ValueError, match="cannot be placed"):
        move_catalog_node(session, year.id, root.id, reason="invalid structure")

    moved = move_catalog_node(
        session, group.id, line_node.id, reason="Organize theme group", sort_order=3
    )
    session.commit()

    assert moved.parent_id == line_node.id
    assert moved.sort_order == 3
    event = session.scalar(select(ChangeLog).where(ChangeLog.entity_id == group.id))
    assert event is not None
    assert event.action == "moved"
    assert event.reason == "Organize theme group"
    assert event.old_values == {"parent_id": year.id, "sort_order": 0}
    assert event.new_values == {"parent_id": line_node.id, "sort_order": 3}


def test_product_line_brand_link_does_not_delete_brand(session):
    brand = Brand(name="Hot Wheels")
    line = ProductLine(name="Premium", line_type="premium")
    line.brand_links.append(ProductLineBrand(brand=brand))
    session.add(line)
    session.commit()

    session.delete(line)
    session.commit()
    assert session.get(Brand, brand.id) is not None


def test_series_and_release_identity_are_unchanged_by_tree_placement(session):
    casting = Casting(name="Nissan Skyline")
    release = Release(casting=casting, catalog_year=2026)
    series = Series(name="J-Imports")
    root = CatalogNode(node_type="root")
    session.add_all([release, series, root])
    session.flush()
    series_node = CatalogNode(node_type="series", parent=root, series=series)
    release_node = CatalogNode(node_type="release", parent=series_node, release=release)
    session.add_all([series_node, release_node])
    session.commit()

    release_id = release.id
    casting_id = casting.id
    series_id = series.id
    move_catalog_node(session, release_node.id, root.id, reason="Reorganize catalog")
    session.commit()

    assert session.get(Release, release_id).casting_id == casting_id
    assert session.get(Series, series_id) is not None

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import CatalogNode, Casting, ChangeLog, ProductLine, Release


def _test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _override_db(engine):
    def override_get_db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db


def test_catalog_tree_returns_typed_hierarchy_and_labels():
    engine = _test_engine()
    try:
        with Session(engine) as session:
            root = CatalogNode(node_type="root", label_override="HW Catalog")
            line = ProductLine(name="Mainline", line_type="mainline")
            session.add_all([root, line])
            session.flush()
            line_node = CatalogNode(
                parent=root, node_type="product_line", product_line=line
            )
            session.add(line_node)
            session.flush()
            year = CatalogNode(
                parent=line_node, node_type="year", catalog_year=2026
            )
            session.add(year)
            session.commit()
            root_id = root.id

        _override_db(engine)
        response = TestClient(app).get("/catalog/tree")
        assert response.status_code == 200
        root_json = response.json()["items"][0]
        assert root_json["id"] == root_id
        assert root_json["label"] == "HW Catalog"
        assert root_json["children"][0]["label"] == "Mainline"
        assert root_json["children"][0]["children"][0]["label"] == "2026"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_catalog_tree_returns_404_for_unknown_subtree():
    engine = _test_engine()
    try:
        _override_db(engine)
        response = TestClient(app).get("/catalog/tree?parent_id=missing")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_catalog_node_move_api_audits_move_and_preserves_release_identity():
    engine = _test_engine()
    try:
        with Session(engine) as session:
            root = CatalogNode(node_type="root")
            group_a = CatalogNode(node_type="group", parent=root, label_override="A")
            group_b = CatalogNode(node_type="group", parent=root, label_override="B")
            casting = Casting(name="Nissan Skyline")
            release = Release(casting=casting, catalog_year=2026)
            session.add_all([root, group_a, group_b, release])
            session.flush()
            release_node = CatalogNode(
                node_type="release", parent=group_a, release=release
            )
            session.add(release_node)
            session.commit()
            node_id = release_node.id
            group_b_id = group_b.id
            release_id = release.id
            casting_id = casting.id

        _override_db(engine)
        response = TestClient(app).post(
            f"/catalog/nodes/{node_id}/move",
            json={
                "new_parent_id": group_b_id,
                "reason": "Organize the import series",
                "sort_order": 2,
            },
        )
        assert response.status_code == 200
        assert response.json()["parent_id"] == group_b_id
        assert response.json()["release_id"] == release_id

        with Session(engine) as session:
            moved = session.get(CatalogNode, node_id)
            assert moved.parent_id == group_b_id
            assert moved.release_id == release_id
            assert session.get(Release, release_id).casting_id == casting_id
            audit = session.query(ChangeLog).filter_by(
                entity_type="catalog_node", entity_id=node_id, action="moved"
            ).one()
            assert audit.reason == "Organize the import series"
            assert audit.old_values["parent_id"] is not None
            assert audit.new_values["parent_id"] == group_b_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_catalog_node_move_api_rejects_invalid_parent_type():
    engine = _test_engine()
    try:
        with Session(engine) as session:
            root = CatalogNode(node_type="root")
            line = ProductLine(name="Mainline", line_type="mainline")
            line_node = CatalogNode(
                node_type="product_line", product_line=line, parent=root
            )
            year = CatalogNode(node_type="year", catalog_year=2026, parent=line_node)
            session.add_all([root, line, line_node, year])
            session.commit()
            line_id = line_node.id
            year_id = year.id

        _override_db(engine)
        response = TestClient(app).post(
            f"/catalog/nodes/{line_id}/move",
            json={"new_parent_id": year_id, "reason": "Invalid move"},
        )
        assert response.status_code == 422
        assert "cannot be placed" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()



def test_catalog_api_allows_configured_local_ui_origin_for_preflight():
    response = TestClient(app).options(
        "/catalog/nodes/example/move",
        headers={
            "Origin": "http://localhost:5500",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"
    assert "POST" in response.headers["access-control-allow-methods"]

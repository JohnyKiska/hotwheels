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


def test_catalog_tree_move_flow_updates_tree_and_rejects_invalid_move_without_side_effects():
    engine = _test_engine()
    try:
        with Session(engine) as session:
            root = CatalogNode(node_type="root", label_override="HW Catalog")
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
            root_id = root.id
            group_a_id = group_a.id
            group_b_id = group_b.id
            release_node_id = release_node.id
            release_id = release.id
            casting_id = casting.id

        _override_db(engine)
        client = TestClient(app)

        before = client.get("/catalog/tree")
        assert before.status_code == 200
        before_root = before.json()["items"][0]
        before_groups = {node["label"]: node for node in before_root["children"]}
        assert before_groups["A"]["children"][0]["id"] == release_node_id
        assert before_groups["B"]["children"] == []

        moved = client.post(
            f"/catalog/nodes/{release_node_id}/move",
            json={
                "new_parent_id": group_b_id,
                "reason": "End-to-end integration test",
                "sort_order": 3,
                "actor_type": "test",
            },
        )
        assert moved.status_code == 200
        assert moved.json()["parent_id"] == group_b_id
        assert moved.json()["release_id"] == release_id

        after = client.get("/catalog/tree")
        assert after.status_code == 200
        after_root = after.json()["items"][0]
        after_groups = {node["label"]: node for node in after_root["children"]}
        assert after_groups["A"]["children"] == []
        assert after_groups["B"]["children"][0]["id"] == release_node_id
        assert after_groups["B"]["children"][0]["release_id"] == release_id

        invalid = client.post(
            f"/catalog/nodes/{group_b_id}/move",
            json={
                "new_parent_id": release_node_id,
                "reason": "This parent type is not allowed",
            },
        )
        assert invalid.status_code == 422

        # A rejected move must not change the saved tree or append another audit row.
        after_rejection = client.get("/catalog/tree")
        assert after_rejection.status_code == 200
        rejected_root = after_rejection.json()["items"][0]
        rejected_groups = {node["label"]: node for node in rejected_root["children"]}
        assert rejected_groups["B"]["parent_id"] == root_id
        assert rejected_groups["B"]["children"][0]["id"] == release_node_id

        with Session(engine) as session:
            stored_release = session.get(Release, release_id)
            assert stored_release.casting_id == casting_id
            assert session.get(CatalogNode, release_node_id).release_id == release_id
            audits = (
                session.query(ChangeLog)
                .filter_by(
                    entity_type="catalog_node",
                    entity_id=release_node_id,
                    action="moved",
                )
                .all()
            )
            assert len(audits) == 1
            assert audits[0].reason == "End-to-end integration test"
            assert audits[0].old_values["parent_id"] == group_a_id
            assert audits[0].new_values["parent_id"] == group_b_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()

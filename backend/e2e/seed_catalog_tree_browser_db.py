"""Seed a disposable SQLite database for the browser E2E workflow.

Run only in the fresh GitHub Actions workspace created for this workflow.
No production or user catalog data is loaded.
"""
from app import models  # noqa: F401 - register all SQLAlchemy models
from app.db import Base, SessionLocal, engine
from app.models import CatalogNode, Casting, Release

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

with SessionLocal() as session:
    root = CatalogNode(node_type="root", label_override="E2E Catalog")
    group_a = CatalogNode(node_type="group", parent=root, label_override="E2E Group A")
    group_b = CatalogNode(node_type="group", parent=root, label_override="E2E Group B")
    casting = Casting(name="E2E Nissan Skyline")
    release = Release(casting=casting, catalog_year=2026)
    session.add_all([root, group_a, group_b, release])
    session.flush()
    release_node = CatalogNode(
        node_type="release", parent=group_a, release=release,
        label_override="E2E Skyline Release",
    )
    session.add(release_node)
    session.commit()
    print(
        "Seeded isolated browser E2E database:",
        {"release_node_id": release_node.id, "release_id": release.id, "casting_id": casting.id},
    )

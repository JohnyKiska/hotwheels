from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.db import Base
from app.models import (
    Casting,
    Evidence,
    EvidenceProductLine,
    ProductLine,
    Release,
    ReleaseProductLine,
    Source,
    SourceRecord,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
REVISION = "20261123_product_line_tables"
PREVIOUS_REVISION = "20261123_release_nullable_casting"
PRODUCT_LINE_TABLES = {
    "product_lines",
    "release_product_lines",
    "evidence_product_lines",
}


def migration_config(database_url: str, monkeypatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def sqlite_engine(database_url: str):
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


def test_product_line_migration_clean_database_upgrade(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'clean-product-line.db'}"
    config = migration_config(database_url, monkeypatch)

    command.upgrade(config, "head")

    engine = sqlite_engine(database_url)
    try:
        inspector = inspect(engine)
        assert PRODUCT_LINE_TABLES <= set(inspector.get_table_names())
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == REVISION
    finally:
        engine.dispose()


def test_product_line_migration_upgrades_existing_schema_without_product_lines(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'existing-schema.db'}"
    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, PREVIOUS_REVISION)

    engine = sqlite_engine(database_url)
    with Session(engine) as db:
        casting = Casting(name="Existing casting")
        db.add(Release(casting=casting, catalog_year=2026))
        db.commit()
        casting_id = casting.id
    assert not (PRODUCT_LINE_TABLES & set(inspect(engine).get_table_names()))
    engine.dispose()

    command.upgrade(config, "head")

    engine = sqlite_engine(database_url)
    try:
        assert PRODUCT_LINE_TABLES <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT name FROM castings WHERE id = :id"),
                {"id": casting_id},
            ).scalar_one() == "Existing casting"
    finally:
        engine.dispose()


def test_product_line_migration_accepts_metadata_created_tables(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'metadata-created.db'}"
    engine = sqlite_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        product_line = ProductLine(
            code="premium",
            name="Premium",
            normalized_name="premium",
        )
        db.add(product_line)
        db.commit()
        product_line_id = product_line.id
    engine.dispose()

    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, "head")

    engine = sqlite_engine(database_url)
    try:
        with Session(engine) as db:
            assert db.get(ProductLine, product_line_id) is not None
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == REVISION
    finally:
        engine.dispose()


def test_product_line_migration_repeated_upgrade_head_is_idempotent(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'repeat-upgrade.db'}"
    config = migration_config(database_url, monkeypatch)

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    engine = sqlite_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM alembic_version")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == REVISION
    finally:
        engine.dispose()


def test_product_line_migration_constraints_and_indexes(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'constraints.db'}"
    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, "head")

    engine = sqlite_engine(database_url)
    try:
        inspector = inspect(engine)
        assert inspector.get_pk_constraint("product_lines")["constrained_columns"] == ["id"]
        assert inspector.get_pk_constraint("release_product_lines")["constrained_columns"] == ["id"]
        assert inspector.get_pk_constraint("evidence_product_lines")["constrained_columns"] == [
            "evidence_id",
            "release_product_line_id",
        ]

        assert {
            (item["name"], tuple(item["column_names"]))
            for item in inspector.get_unique_constraints("product_lines")
        } == {
            ("uq_product_lines_code", ("code",)),
            ("uq_product_lines_normalized_name", ("normalized_name",)),
        }
        assert {
            (item["name"], tuple(item["column_names"]))
            for item in inspector.get_unique_constraints("release_product_lines")
        } == {
            (
                "uq_release_product_lines_pair",
                ("release_id", "product_line_id"),
            ),
        }
        assert inspector.get_unique_constraints("evidence_product_lines") == []

        assert {
            (item["name"], " ".join(item["sqltext"].split()))
            for item in inspector.get_check_constraints("product_lines")
        } == {
            (
                "ck_product_lines_status",
                "status IN ('candidate', 'under_review', 'confirmed', 'rejected')",
            ),
            (
                "ck_product_lines_not_own_parent",
                "parent_product_line_id IS NULL OR parent_product_line_id != id",
            ),
        }
        assert {
            (item["name"], " ".join(item["sqltext"].split()))
            for item in inspector.get_check_constraints("release_product_lines")
        } == {
            (
                "ck_release_product_lines_membership_status",
                "membership_status IN ('active', 'withdrawn')",
            ),
        }
        assert inspector.get_check_constraints("evidence_product_lines") == []

        expected_foreign_keys = {
            "product_lines": {
                (("parent_product_line_id",), "product_lines", ("id",), "RESTRICT"),
            },
            "release_product_lines": {
                (("release_id",), "releases", ("id",), "RESTRICT"),
                (("product_line_id",), "product_lines", ("id",), "RESTRICT"),
            },
            "evidence_product_lines": {
                (("evidence_id",), "evidence", ("id",), "CASCADE"),
                (
                    ("release_product_line_id",),
                    "release_product_lines",
                    ("id",),
                    "RESTRICT",
                ),
            },
        }
        for table_name, expected in expected_foreign_keys.items():
            actual = {
                (
                    tuple(item["constrained_columns"]),
                    item["referred_table"],
                    tuple(item["referred_columns"]),
                    (item.get("options") or {}).get("ondelete", "").upper(),
                )
                for item in inspector.get_foreign_keys(table_name)
            }
            assert actual == expected

        expected_indexes = {
            "product_lines": {
                ("ix_product_lines_parent_product_line_id", ("parent_product_line_id",)),
            },
            "release_product_lines": {
                ("ix_release_product_lines_product_line_id", ("product_line_id",)),
            },
            "evidence_product_lines": {
                (
                    "ix_evidence_product_lines_release_product_line_id",
                    ("release_product_line_id",),
                ),
            },
        }
        for table_name, expected in expected_indexes.items():
            actual = {
                (item["name"], tuple(item["column_names"]))
                for item in inspector.get_indexes(table_name)
            }
            assert actual == expected

        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

        with Session(engine) as db:
            valid_line = ProductLine(
                code="valid",
                name="Valid",
                normalized_name="valid",
            )
            db.add(valid_line)
            db.commit()

            db.add(ProductLine(
                code="orphan",
                name="Orphan",
                normalized_name="orphan",
                parent_product_line_id="missing-parent",
            ))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()

            db.add(ProductLine(
                code="bad-status",
                name="Bad status",
                normalized_name="bad-status",
                status="published",
            ))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    finally:
        engine.dispose()


def test_product_line_migration_rejects_incompatible_existing_table(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'incompatible-table.db'}"
    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, PREVIOUS_REVISION)

    engine = sqlite_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE product_lines (id VARCHAR(36) NOT NULL PRIMARY KEY)"
        )
    engine.dispose()

    with pytest.raises(
        RuntimeError,
        match="incompatible existing table 'product_lines'",
    ):
        command.upgrade(config, "head")

    engine = sqlite_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == PREVIOUS_REVISION
    finally:
        engine.dispose()


def test_product_line_migration_downgrade_drops_empty_tables(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'empty-downgrade.db'}"
    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, "head")

    command.downgrade(config, PREVIOUS_REVISION)

    engine = sqlite_engine(database_url)
    try:
        assert not (PRODUCT_LINE_TABLES & set(inspect(engine).get_table_names()))
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == PREVIOUS_REVISION
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "data_kind", ["product_line", "release_product_line", "evidence_product_line"]
)
def test_product_line_migration_downgrade_refuses_existing_data(
    tmp_path, monkeypatch, data_kind
):
    database_url = f"sqlite:///{tmp_path / f'downgrade-{data_kind}.db'}"
    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, "head")

    engine = sqlite_engine(database_url)
    with Session(engine) as db:
        product_line = ProductLine(
            code="premium",
            name="Premium",
            normalized_name="premium",
        )
        db.add(product_line)

        if data_kind != "product_line":
            release = Release(casting=Casting(name="Downgrade casting"))
            assignment = ReleaseProductLine(
                release=release,
                product_line=product_line,
            )
            db.add(assignment)

            if data_kind == "evidence_product_line":
                evidence = Evidence(
                    source_record=SourceRecord(
                        source=Source(name="Downgrade source", source_type="test"),
                        record_type="catalog_entry",
                    ),
                    attribute_name="product_line",
                    observed_value="Premium",
                )
                evidence.product_line_links.append(
                    EvidenceProductLine(release_product_line=assignment)
                )
                db.add(evidence)
        db.commit()
    engine.dispose()

    with pytest.raises(
        RuntimeError,
        match="Cannot downgrade ProductLine migration while data exists",
    ):
        command.downgrade(config, PREVIOUS_REVISION)

    engine = sqlite_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == REVISION
        assert PRODUCT_LINE_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from app import models
from app.db import Base


BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "20261117_media_library"
EBAY_TABLES = {"ebay_sellers", "ebay_listings", "ebay_notifications"}
STATE_TABLE = "alembic_20261119_ebay_notifications_state"


def migration_config(database_url: str, monkeypatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def existing_tables(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_clean_database_upgrade_and_repeated_downgrade(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'clean.db'}"
    config = migration_config(database_url, monkeypatch)

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    tables = existing_tables(database_url)
    assert EBAY_TABLES <= tables
    assert "alembic_20261119_ebay_notifications_state" in tables

    command.downgrade(config, PREVIOUS_REVISION)
    command.downgrade(config, PREVIOUS_REVISION)

    tables = existing_tables(database_url)
    assert not (EBAY_TABLES | {"alembic_20261119_ebay_notifications_state"}) & tables
    assert {"castings", "sources", "evidence"} <= tables


def test_all_preexisting_ebay_tables_and_rows_survive_downgrade(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'all-existing.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(
        engine,
        tables=[Base.metadata.tables[name] for name in sorted(EBAY_TABLES)],
    )
    with Session(engine) as db:
        seller = models.EbaySeller(
            ebay_user_id="preexisting-user",
            username="preexisting-seller",
        )
        db.add(seller)
        db.flush()
        db.add(models.EbayListing(
            ebay_item_id="preexisting-item",
            seller_id=seller.id,
            title="Existing listing",
        ))
        db.add(models.EbayNotification(
            notification_id="preexisting-notification",
            topic="TEST",
            payload_sha256="preexisting-hash",
        ))
        db.commit()
    engine.dispose()

    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.downgrade(config, PREVIOUS_REVISION)
    command.downgrade(config, PREVIOUS_REVISION)

    assert EBAY_TABLES <= existing_tables(database_url)
    engine = create_engine(database_url)
    try:
        with Session(engine) as db:
            assert db.scalar(select(models.EbaySeller.username)) == "preexisting-seller"
            assert db.scalar(select(models.EbayListing.title)) == "Existing listing"
            assert db.scalar(
                select(models.EbayNotification.payload_sha256)
            ) == "preexisting-hash"
    finally:
        engine.dispose()


def test_partial_preexisting_tables_only_migration_created_tables_are_dropped(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'partial-existing.db'}"
    engine = create_engine(database_url)
    preexisting = [
        Base.metadata.tables["ebay_sellers"],
        Base.metadata.tables["ebay_notifications"],
    ]
    Base.metadata.create_all(engine, tables=preexisting)
    with Session(engine) as db:
        seller = models.EbaySeller(
            ebay_user_id="partial-user",
            username="partial-seller",
        )
        db.add(seller)
        db.add(models.EbayNotification(
            notification_id="partial-notification",
            topic="TEST",
            payload_sha256="partial-hash",
        ))
        db.commit()
    engine.dispose()

    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert EBAY_TABLES <= existing_tables(database_url)

    command.downgrade(config, PREVIOUS_REVISION)
    command.downgrade(config, PREVIOUS_REVISION)

    tables = existing_tables(database_url)
    assert {"ebay_sellers", "ebay_notifications"} <= tables
    assert "ebay_listings" not in tables
    assert "alembic_20261119_ebay_notifications_state" not in tables
    engine = create_engine(database_url)
    try:
        with Session(engine) as db:
            assert db.scalar(select(models.EbaySeller.username)) == "partial-seller"
            assert db.scalar(
                select(models.EbayNotification.payload_sha256)
            ) == "partial-hash"
            assert db.scalar(select(func.count()).select_from(models.Casting)) == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("state_kind", ["foreign_owner", "incompatible_schema"])
def test_preexisting_migration_state_table_is_rejected_unchanged(
    tmp_path, monkeypatch, state_kind
):
    database_url = f"sqlite:///{tmp_path / f'{state_kind}.db'}"
    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, PREVIOUS_REVISION)

    engine = create_engine(database_url)
    with engine.begin() as connection:
        if state_kind == "foreign_owner":
            connection.exec_driver_sql(
                f"CREATE TABLE {STATE_TABLE} ("
                "table_name VARCHAR(64) PRIMARY KEY, "
                "created_by_migration BOOLEAN NOT NULL, "
                "revision_id VARCHAR(64) NOT NULL)"
            )
            connection.execute(
                text(
                    f"INSERT INTO {STATE_TABLE} "
                    "(table_name, created_by_migration, revision_id) "
                    "VALUES ('__owner__', 0, 'another_revision')"
                )
            )
            expected_error = "owner revision"
        else:
            connection.exec_driver_sql(
                f"CREATE TABLE {STATE_TABLE} (sentinel TEXT)"
            )
            connection.execute(
                text(f"INSERT INTO {STATE_TABLE} (sentinel) VALUES ('keep-me')")
            )
            expected_error = "incompatible migration state table"

    with pytest.raises(RuntimeError, match=expected_error):
        command.upgrade(config, "head")

    with engine.connect() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns(STATE_TABLE)
        }
        if state_kind == "foreign_owner":
            owner = connection.execute(
                text(
                    f"SELECT table_name, created_by_migration, revision_id "
                    f"FROM {STATE_TABLE}"
                )
            ).one()
            assert tuple(owner) == ("__owner__", 0, "another_revision")
            assert columns == {
                "table_name",
                "created_by_migration",
                "revision_id",
            }
        else:
            assert connection.execute(
                text(f"SELECT sentinel FROM {STATE_TABLE}")
            ).scalar_one() == "keep-me"
            assert columns == {"sentinel"}
        version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert version == PREVIOUS_REVISION
    assert not (EBAY_TABLES & existing_tables(database_url))
    engine.dispose()


def test_repeated_upgrade_resumes_owned_partial_state(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'owned-partial.db'}"
    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, PREVIOUS_REVISION)

    engine = create_engine(database_url)
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables["ebay_sellers"],
            Base.metadata.tables["ebay_listings"],
        ],
    )
    with Session(engine) as db:
        seller = models.EbaySeller(
            ebay_user_id="partial-owner",
            username="keep-this-seller",
        )
        db.add(seller)
        db.flush()
        db.add(models.EbayListing(
            ebay_item_id="partial-owned-listing",
            seller_id=seller.id,
            title="Owned by the in-progress migration",
        ))
        db.commit()
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE {STATE_TABLE} ("
            "table_name VARCHAR(64) PRIMARY KEY, "
            "created_by_migration BOOLEAN NOT NULL, "
            "revision_id VARCHAR(64) NOT NULL)"
        )
        connection.execute(
            text(
                f"INSERT INTO {STATE_TABLE} "
                "(table_name, created_by_migration, revision_id) VALUES "
                "('__owner__', 0, '20261119_ebay_notifications'), "
                "('ebay_sellers', 0, '20261119_ebay_notifications'), "
                "('ebay_listings', 1, '20261119_ebay_notifications')"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        states = dict(connection.execute(
            text(
                f"SELECT table_name, created_by_migration "
                f"FROM {STATE_TABLE} WHERE table_name != '__owner__'"
            )
        ).all())
    assert states == {
        "ebay_sellers": 0,
        "ebay_listings": 1,
        "ebay_notifications": 1,
    }

    command.downgrade(config, PREVIOUS_REVISION)
    command.downgrade(config, PREVIOUS_REVISION)

    tables = existing_tables(database_url)
    assert "ebay_sellers" in tables
    assert "ebay_listings" not in tables
    assert "ebay_notifications" not in tables
    assert STATE_TABLE not in tables
    with Session(engine) as db:
        assert db.scalar(select(models.EbaySeller.username)) == "keep-this-seller"
    engine.dispose()


def test_downgrade_refuses_foreign_migration_state_table(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'foreign-state-on-downgrade.db'}"
    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP TABLE {STATE_TABLE}")
        connection.exec_driver_sql(
            f"CREATE TABLE {STATE_TABLE} ("
            "table_name VARCHAR(64) PRIMARY KEY, "
            "created_by_migration BOOLEAN NOT NULL, "
            "revision_id VARCHAR(64) NOT NULL)"
        )
        connection.execute(
            text(
                f"INSERT INTO {STATE_TABLE} "
                "(table_name, created_by_migration, revision_id) "
                "VALUES ('__owner__', 0, 'another_revision')"
            )
        )

    with pytest.raises(RuntimeError, match="owner revision"):
        command.downgrade(config, PREVIOUS_REVISION)

    with engine.connect() as connection:
        owner = connection.execute(
            text(
                f"SELECT table_name, created_by_migration, revision_id "
                f"FROM {STATE_TABLE}"
            )
        ).one()
        version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert tuple(owner) == ("__owner__", 0, "another_revision")
    assert version == "20261120_import_apply_foundation"
    assert EBAY_TABLES <= existing_tables(database_url)
    engine.dispose()

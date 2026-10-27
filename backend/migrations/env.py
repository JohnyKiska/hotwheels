"""Alembic environment for the Hot Wheels catalog backend."""
from logging.config import fileConfig
import os
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Running from backend/ is the documented command, but support other cwd values.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: E402,F401
from app.db import Base  # noqa: E402

target_metadata = Base.metadata


def database_url() -> str:
    return os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        with connectable.connect() as connection:
            is_sqlite = connection.dialect.name == "sqlite"
            if is_sqlite:
                # SQLAlchemy 2.x autobegins a transaction for this statement.
                # Commit it before Alembic starts its migration transaction;
                # otherwise the version-row write can be rolled back on close.
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                # SQLite's default Alembic implementation treats DDL as
                # non-transactional. For this migration, explicitly manage
                # the transaction so the alembic_version write is committed
                # along with the migration bookkeeping.
                transactional_ddl=True if is_sqlite else None,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

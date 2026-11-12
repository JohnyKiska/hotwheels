from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .storage import resolve_database_url

DATABASE_URL = resolve_database_url()
database_url = make_url(DATABASE_URL)

engine_options = {}
if database_url.get_backend_name() == "sqlite":
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)


def enable_sqlite_foreign_keys(connection, _record):
    """Enable foreign-key enforcement for SQLite connections only."""
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


if engine.dialect.name == "sqlite":
    event.listen(engine, "connect", enable_sqlite_foreign_keys)


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

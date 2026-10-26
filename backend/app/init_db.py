"""Explicit local database initialization command."""
from . import models  # noqa: F401 - register model metadata with Base
from .db import Base, engine


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    initialize_database()
    print("SQLite tables initialized. No catalog data was imported.")

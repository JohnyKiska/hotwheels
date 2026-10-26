from app import models  # noqa: F401
from app.db import Base, engine


def initialize_database() -> None:
    """Create missing tables for local development only.

    Production schema changes will use Alembic migrations; this helper is for
    early local smoke tests and does not modify existing tables.
    """
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    initialize_database()
    print("Database tables are ready.")

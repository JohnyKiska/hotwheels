"""Complete the initial ORM schema for databases created by the early migration chain.

The first migrations introduced supporting tables before the core catalog tables
existed. SQLite permits foreign keys to reference tables that are not present,
so Alembic could reach head with an incomplete schema. This migration creates
every table declared by the current ORM metadata, adding only missing tables.
"""

from alembic import op


revision = "20261030_core_schema"
down_revision = "20261029_origin_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Import models to register the complete metadata before create_all.
    from app import models  # noqa: F401
    from app.db import Base

    # SQLAlchemy creates missing tables in dependency order and leaves existing
    # tables and their data untouched.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # Intentionally retain the tables. Some installations may have been
    # initialized earlier with app.init_db, and dropping ORM tables here could
    # destroy user data. This is a forward-only schema-completion migration.
    pass

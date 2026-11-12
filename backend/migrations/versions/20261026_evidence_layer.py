"""Create the core catalog schema and evidence/source history tables.

The original migration was first applied to databases whose core tables had
already been created by the development bootstrap. Creating the core tables
here as well makes a clean Alembic upgrade possible. SQLAlchemy's create_all
skips tables that already exist, preserving data in initialized databases.
"""
from alembic import op

revision = "20261026_evidence_layer"
down_revision = None
branch_labels = None
depends_on = None

CORE_TABLES = (
    "castings",
    "casting_variants",
    "series",
    "releases",
    "release_series",
)

EVIDENCE_TABLES = (
    "change_log_evidence", "conflict_evidence", "evidence_series",
    "evidence_releases", "evidence_casting_variants", "evidence_castings",
    "media_assets", "change_log", "conflicts", "evidence", "source_records", "sources",
)


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    tables = CORE_TABLES + EVIDENCE_TABLES
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in tables],
    )


def downgrade():
    from app.db import Base

    bind = op.get_bind()
    tables = CORE_TABLES + EVIDENCE_TABLES
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in reversed(tables)],
    )

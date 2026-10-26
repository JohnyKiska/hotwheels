"""Create evidence, source, conflict, media, and change-history tables.

This migration uses the application's SQLAlchemy metadata for these new tables.
It intentionally does not alter core casting/release tables or import collection.json.
"""
from alembic import op

revision = "20261026_evidence_layer"
down_revision = None
branch_labels = None
depends_on = None

TABLES = (
    "change_log_evidence", "conflict_evidence", "evidence_series",
    "evidence_releases", "evidence_casting_variants", "evidence_castings",
    "media_assets", "change_log", "conflicts", "evidence", "source_records", "sources",
)


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[name] for name in TABLES])


def downgrade():
    from app.db import Base
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[name] for name in reversed(TABLES)])

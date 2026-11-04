"""Add explicit release links to catalog conflicts.

This migration is based directly on the current integration schema. It is
intentionally independent of the later core-schema migration from PR #74.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261104_conflict_releases"
down_revision = "20261027_change_log_append_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Base.metadata.create_all() may have created this table already when
    # upgrading a database initialized from the current ORM models.
    if not sa.inspect(op.get_bind()).has_table("conflict_releases"):
        op.create_table(
            "conflict_releases",
            sa.Column("conflict_id", sa.String(length=36),
                      sa.ForeignKey("conflicts.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("release_id", sa.String(length=36),
                      sa.ForeignKey("releases.id", ondelete="RESTRICT"), primary_key=True),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="affected"),
            sa.Column("note", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("conflict_releases"):
        op.drop_table("conflict_releases")

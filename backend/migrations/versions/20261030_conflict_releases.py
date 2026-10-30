"""Add explicit release links to catalog conflicts."""
from alembic import op
import sqlalchemy as sa


revision = "20261030_conflict_releases"
down_revision = "20261030_core_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The core-schema migration uses ORM metadata.create_all(), which may
    # already have created this table on a fresh database.
    if not sa.inspect(op.get_bind()).has_table("conflict_releases"):
        op.create_table(
            "conflict_releases",
            sa.Column("conflict_id", sa.String(length=36), sa.ForeignKey("conflicts.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("release_id", sa.String(length=36), sa.ForeignKey("releases.id", ondelete="RESTRICT"), primary_key=True),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="affected"),
            sa.Column("note", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("conflict_releases"):
        op.drop_table("conflict_releases")

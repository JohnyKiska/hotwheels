"""Create the minimal catalog-tree tables used by read-only grouping preview.

The former ORM models were retired from the current application metadata, but
the live grouping adapter still reads product_lines and catalog_nodes. Keep
this migration self-contained and safe for databases where these tables already
exist.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261029_catalog_tree"
down_revision = "20261029_manufacturer_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("product_lines"):
        op.create_table(
            "product_lines",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=240), nullable=False),
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table("catalog_nodes"):
        op.create_table(
            "catalog_nodes",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("parent_id", sa.String(length=36), nullable=True),
            sa.Column("node_type", sa.String(length=24), nullable=False),
            sa.Column("product_line_id", sa.String(length=36), nullable=True),
            sa.Column("release_id", sa.String(length=36), nullable=True),
            sa.ForeignKeyConstraint(
                ["parent_id"], ["catalog_nodes.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["product_line_id"], ["product_lines.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["release_id"], ["releases.id"], ondelete="RESTRICT"
            ),
        )


def downgrade() -> None:
    # These tables may contain catalog navigation data. Preserve them.
    pass

"""Retain the historical origin-reference revision in the Alembic graph.

Origin-reference ORM models are no longer part of the current application
metadata. Existing databases retain any legacy origin tables and their data.
"""

revision = "20261029_origin_reference"
down_revision = "20261029_catalog_tree"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical origin-reference models are no longer registered.
    pass


def downgrade() -> None:
    # Preserve any legacy origin-reference data.
    pass

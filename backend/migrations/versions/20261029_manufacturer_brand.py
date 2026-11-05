"""Retain the historical manufacturer/brand revision in the Alembic graph.

The current application no longer maps manufacturer and brand tables. Existing
installations keep their tables and data; fresh databases use current ORM
metadata and do not recreate retired models.
"""

revision = "20261029_manufacturer_brand"
down_revision = "20261029_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical manufacturer/brand ORM models are no longer registered.
    pass


def downgrade() -> None:
    # Never drop legacy manufacturer/brand data during a downgrade.
    pass

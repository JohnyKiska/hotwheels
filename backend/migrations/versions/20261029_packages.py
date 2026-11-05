"""Retain the historical package-schema revision in the Alembic graph.

The current application no longer maps package tables. Existing databases keep
any package tables and data they already contain; fresh databases are built
from the current ORM metadata by the core-schema migration.
"""

revision = "20261029_packages"
down_revision = "20261027_change_log_append_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deliberately do not recreate retired package models from historical ORM
    # metadata that is no longer part of the current application.
    pass


def downgrade() -> None:
    # Preserve any package tables and data left by older installations.
    pass

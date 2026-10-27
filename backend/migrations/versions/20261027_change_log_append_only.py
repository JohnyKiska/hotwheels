"""Protect the audit journal from updates and deletes in SQLite.

ChangeLog rows are historical facts. Corrections must be recorded as new rows,
not by rewriting or deleting the original entry.
"""
from alembic import op

revision = "20261027_change_log_append_only"
down_revision = "20261027_catalog_identifiers"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TRIGGER change_log_no_update
        BEFORE UPDATE ON change_log
        BEGIN
            SELECT RAISE(ABORT, 'change_log is append-only; insert a correction instead');
        END
    """)
    op.execute("""
        CREATE TRIGGER change_log_no_delete
        BEFORE DELETE ON change_log
        BEGIN
            SELECT RAISE(ABORT, 'change_log is append-only; historical entries cannot be deleted');
        END
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS change_log_no_delete")
    op.execute("DROP TRIGGER IF EXISTS change_log_no_update")

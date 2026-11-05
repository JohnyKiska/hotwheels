"""Create append-only Casting grouping review workflow tables.

This migration stores immutable preview snapshots and reviewer decisions only.
It does not alter catalog entities or evidence.
"""
from alembic import op

revision = "20261105_casting_grouping_review"
down_revision = "20261027_change_log_append_only"
branch_labels = None
depends_on = None

TABLES = (
    "casting_grouping_review_sessions",
    "casting_grouping_review_decisions",
)


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in TABLES],
    )
    op.execute("""
        CREATE TRIGGER casting_grouping_review_sessions_no_update
        BEFORE UPDATE ON casting_grouping_review_sessions
        BEGIN
            SELECT RAISE(ABORT, 'review session snapshots are immutable');
        END
    """)
    op.execute("""
        CREATE TRIGGER casting_grouping_review_sessions_no_delete
        BEFORE DELETE ON casting_grouping_review_sessions
        BEGIN
            SELECT RAISE(ABORT, 'review session snapshots are immutable');
        END
    """)
    op.execute("""
        CREATE TRIGGER casting_grouping_review_decisions_no_update
        BEFORE UPDATE ON casting_grouping_review_decisions
        BEGIN
            SELECT RAISE(ABORT, 'review decisions are append-only');
        END
    """)
    op.execute("""
        CREATE TRIGGER casting_grouping_review_decisions_no_delete
        BEFORE DELETE ON casting_grouping_review_decisions
        BEGIN
            SELECT RAISE(ABORT, 'review decisions are append-only');
        END
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS casting_grouping_review_decisions_no_delete")
    op.execute("DROP TRIGGER IF EXISTS casting_grouping_review_decisions_no_update")
    op.execute("DROP TRIGGER IF EXISTS casting_grouping_review_sessions_no_delete")
    op.execute("DROP TRIGGER IF EXISTS casting_grouping_review_sessions_no_update")
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in reversed(TABLES)],
    )

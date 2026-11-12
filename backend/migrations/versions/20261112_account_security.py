"""Add server sessions, invitations, email verification and account audit events.

Session bearer values and one-time tokens are stored only as cryptographic hashes.
Account audit events are protected against UPDATE and DELETE at the database layer.
"""
import sqlalchemy as sa
from alembic import op

revision = "20261112_account_security"
down_revision = "20261112_account_rbac"
branch_labels = None
depends_on = None

TABLES = (
    "user_sessions",
    "invitations",
    "email_verification_tokens",
    "audit_events",
)


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in TABLES],
    )

    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute("""
            CREATE TRIGGER audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events is append-only; insert a correction instead');
            END
        """)
        op.execute("""
            CREATE TRIGGER audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events is append-only; historical entries cannot be deleted');
            END
        """)
    elif dialect == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_audit_event_mutation()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'UPDATE' THEN
                    RAISE EXCEPTION 'audit_events is append-only; insert a correction instead';
                END IF;
                RAISE EXCEPTION 'audit_events is append-only; historical entries cannot be deleted';
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER audit_events_no_update
            BEFORE UPDATE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_event_mutation()
        """)
        op.execute("""
            CREATE TRIGGER audit_events_no_delete
            BEFORE DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_event_mutation()
        """)
    else:
        raise RuntimeError(
            f"Append-only audit_events protection is not implemented for {dialect!r}"
        )


def downgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete")
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_update")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete ON audit_events")
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_audit_event_mutation()")
    else:
        raise RuntimeError(
            f"Append-only audit_events protection is not implemented for {dialect!r}"
        )

    from app.db import Base

    bind = op.get_bind()
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in reversed(TABLES)],
    )

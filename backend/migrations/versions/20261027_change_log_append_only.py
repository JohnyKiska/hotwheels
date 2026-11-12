"""Protect the audit journal from updates and deletes.

SQLite uses native triggers with RAISE(ABORT). PostgreSQL uses a PL/pgSQL
trigger function. Both enforce the same append-only rule at the database layer.
"""
from alembic import op

revision = "20261027_change_log_append_only"
down_revision = "20261027_catalog_identifiers"
branch_labels = None
depends_on = None


def upgrade():
    dialect = op.get_bind().dialect.name

    if dialect == "sqlite":
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
    elif dialect == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_change_log_mutation()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'UPDATE' THEN
                    RAISE EXCEPTION 'change_log is append-only; insert a correction instead';
                END IF;
                RAISE EXCEPTION 'change_log is append-only; historical entries cannot be deleted';
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER change_log_no_update
            BEFORE UPDATE ON change_log
            FOR EACH ROW EXECUTE FUNCTION prevent_change_log_mutation()
        """)
        op.execute("""
            CREATE TRIGGER change_log_no_delete
            BEFORE DELETE ON change_log
            FOR EACH ROW EXECUTE FUNCTION prevent_change_log_mutation()
        """)
    else:
        raise RuntimeError(
            f"Append-only change_log protection is not implemented for {dialect!r}"
        )


def downgrade():
    dialect = op.get_bind().dialect.name

    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS change_log_no_delete")
        op.execute("DROP TRIGGER IF EXISTS change_log_no_update")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS change_log_no_delete ON change_log")
        op.execute("DROP TRIGGER IF EXISTS change_log_no_update ON change_log")
        op.execute("DROP FUNCTION IF EXISTS prevent_change_log_mutation()")
    else:
        raise RuntimeError(
            f"Append-only change_log protection is not implemented for {dialect!r}"
        )

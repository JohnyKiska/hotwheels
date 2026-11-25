"""Allow releases to exist without an assigned casting."""

from alembic import op
import sqlalchemy as sa

revision = "20261123_release_nullable_casting"
down_revision = "20261120_import_apply_foundation"
branch_labels = None
depends_on = None


def _check_foreign_keys(bind):
    violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            f"Foreign key violations detected after migration: {violations}"
        )


def upgrade():
    bind = op.get_bind()

    with op.batch_alter_table("releases", recreate="always") as batch_op:
        batch_op.alter_column(
            "casting_id",
            existing_type=sa.String(length=36),
            existing_nullable=False,
            nullable=True,
        )

    _check_foreign_keys(bind)


def downgrade():
    bind = op.get_bind()

    null_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM releases WHERE casting_id IS NULL")
    ).scalar_one()

    if null_count:
        raise RuntimeError(
            "Cannot downgrade: releases without casting exist. "
            "Assign a casting to every release before downgrading."
        )

    with op.batch_alter_table("releases", recreate="always") as batch_op:
        batch_op.alter_column(
            "casting_id",
            existing_type=sa.String(length=36),
            existing_nullable=True,
            nullable=False,
        )

    _check_foreign_keys(bind)

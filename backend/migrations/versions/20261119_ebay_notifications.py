"""Add isolated eBay seller, listing, and notification tables."""
from alembic import op
import sqlalchemy as sa

revision = "20261119_ebay_notifications"
down_revision = "20261117_media_library"
branch_labels = None
depends_on = None

EBAY_TABLES = ("ebay_sellers", "ebay_listings", "ebay_notifications")
STATE_TABLE = "alembic_20261119_ebay_notifications_state"
OWNER_KEY = "__owner__"


def _migration_state(bind):
    inspector = sa.inspect(bind)
    if not inspector.has_table(STATE_TABLE):
        return None, {}

    columns = {column["name"]: column for column in inspector.get_columns(STATE_TABLE)}
    primary_key = inspector.get_pk_constraint(STATE_TABLE).get("constrained_columns")
    expected_columns = {"table_name", "created_by_migration", "revision_id"}
    if (
        set(columns) != expected_columns
        or primary_key != ["table_name"]
        or not isinstance(columns["table_name"]["type"], sa.String)
        or columns["table_name"]["type"].length != 64
        or not isinstance(columns["created_by_migration"]["type"], sa.Boolean)
        or columns["created_by_migration"]["nullable"]
        or not isinstance(columns["revision_id"]["type"], sa.String)
        or columns["revision_id"]["type"].length != 64
        or columns["revision_id"]["nullable"]
    ):
        raise RuntimeError(
            f"Refusing to use incompatible migration state table {STATE_TABLE}."
        )

    state = sa.table(
        STATE_TABLE,
        sa.column("table_name", sa.String(length=64)),
        sa.column("created_by_migration", sa.Boolean()),
        sa.column("revision_id", sa.String(length=64)),
    )
    records = {}
    for row in bind.execute(
        sa.select(
            state.c.table_name,
            state.c.created_by_migration,
            state.c.revision_id,
        )
    ):
        if row.revision_id != revision:
            raise RuntimeError(
                f"Refusing to use migration state table {STATE_TABLE}: "
                f"owner revision is not {revision}."
            )
        if row.created_by_migration is None:
            raise RuntimeError(
                f"Refusing to use incomplete migration state table {STATE_TABLE}."
            )
        if row.table_name == OWNER_KEY:
            if row.created_by_migration:
                raise RuntimeError(
                    f"Refusing to use invalid owner marker in {STATE_TABLE}."
                )
            continue
        if row.table_name not in EBAY_TABLES or row.table_name in records:
            raise RuntimeError(
                f"Refusing to use invalid migration state in {STATE_TABLE}."
            )
        records[row.table_name] = bool(row.created_by_migration)

    owner = bind.execute(
        sa.select(state.c.table_name).where(state.c.table_name == OWNER_KEY)
    ).first()
    if owner is None:
        raise RuntimeError(
            f"Refusing to use migration state table {STATE_TABLE}: "
            "revision ownership marker is missing."
        )
    return state, records


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    state, recorded_tables = _migration_state(bind)
    if state is None:
        op.create_table(
            STATE_TABLE,
            sa.Column("table_name", sa.String(length=64), primary_key=True),
            sa.Column("created_by_migration", sa.Boolean(), nullable=False),
            sa.Column("revision_id", sa.String(length=64), nullable=False),
        )
        state = sa.table(
            STATE_TABLE,
            sa.column("table_name", sa.String(length=64)),
            sa.column("created_by_migration", sa.Boolean()),
            sa.column("revision_id", sa.String(length=64)),
        )
        bind.execute(
            state.insert().values(
                table_name=OWNER_KEY,
                created_by_migration=False,
                revision_id=revision,
            )
        )

    for table_name in EBAY_TABLES:
        if table_name not in recorded_tables:
            created_by_migration = not sa.inspect(bind).has_table(table_name)
            bind.execute(
                state.insert().values(
                    table_name=table_name,
                    created_by_migration=created_by_migration,
                    revision_id=revision,
                )
            )
            recorded_tables[table_name] = created_by_migration

    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in EBAY_TABLES],
    )


def downgrade():
    bind = op.get_bind()
    state, created_tables = _migration_state(bind)
    if state is None:
        return

    for table_name in reversed(EBAY_TABLES):
        if created_tables.get(table_name) and sa.inspect(bind).has_table(table_name):
            op.drop_table(table_name)

    op.drop_table(STATE_TABLE)

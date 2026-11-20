"""Add stable source codes and idempotent source-record import keys."""
from alembic import op
import sqlalchemy as sa

revision = "20261120_import_apply_foundation"
down_revision = "20261119_ebay_notifications"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    source_columns = {column["name"] for column in inspector.get_columns("sources")}
    if "code" not in source_columns:
        op.add_column("sources", sa.Column("code", sa.String(length=80), nullable=True))

    record_columns = {column["name"] for column in sa.inspect(bind).get_columns("source_records")}
    if "import_key" not in record_columns:
        op.add_column("source_records", sa.Column("import_key", sa.String(length=64), nullable=True))

    inspector = sa.inspect(bind)
    if "ix_sources_code" not in {index["name"] for index in inspector.get_indexes("sources")}:
        op.create_index("ix_sources_code", "sources", ["code"], unique=True)
    if "uq_source_records_source_import_key" not in {index["name"] for index in sa.inspect(bind).get_indexes("source_records")}:
        op.create_index("uq_source_records_source_import_key", "source_records", ["source_id", "import_key"], unique=True)


def downgrade():
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("source_records")}
    if "uq_source_records_source_import_key" in indexes:
        op.drop_index("uq_source_records_source_import_key", table_name="source_records")
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("sources")}
    if "ix_sources_code" in indexes:
        op.drop_index("ix_sources_code", table_name="sources")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("source_records")}
    if "import_key" in columns:
        op.drop_column("source_records", "import_key")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sources")}
    if "code" in columns:
        op.drop_column("sources", "code")

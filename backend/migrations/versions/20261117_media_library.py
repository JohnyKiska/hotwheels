"""Add media library metadata and explicit MediaAsset ↔ Evidence links."""
from alembic import op
import sqlalchemy as sa

revision = "20261117_media_library"
down_revision = "20261112_password_auth"
branch_labels = None
depends_on = None


MEDIA_COLUMNS = (
    sa.Column("category", sa.String(length=32), nullable=False, server_default="reference_photo"),
    sa.Column("angle", sa.String(length=32), nullable=True),
    sa.Column("status", sa.String(length=24), nullable=False, server_default="unreviewed"),
    sa.Column("rights_status", sa.String(length=32), nullable=False, server_default="unknown"),
    sa.Column("rights_holder", sa.String(length=240), nullable=True),
    sa.Column("rights_notes", sa.Text(), nullable=True),
    sa.Column("contributor_name", sa.String(length=240), nullable=True),
    sa.Column("photographer_name", sa.String(length=240), nullable=True),
    sa.Column("uploader_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
    sa.Column("original_media_asset_id", sa.String(length=36), nullable=True),
    sa.Column("width", sa.Integer(), nullable=True),
    sa.Column("height", sa.Integer(), nullable=True),
    sa.Column("byte_size", sa.Integer(), nullable=True),
    sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
)


def upgrade():
    # Some project tests and pre-existing installations bootstrap tables from
    # current SQLAlchemy metadata before running Alembic. Add only missing
    # columns so both clean and already-initialized databases upgrade safely.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("media_assets")}
    for column in MEDIA_COLUMNS:
        if column.name not in existing_columns:
            op.add_column("media_assets", column)

    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("media_assets")}
    if "ix_media_assets_uploader_user_id" not in existing_indexes:
        op.create_index("ix_media_assets_uploader_user_id", "media_assets", ["uploader_user_id"])
    if "ix_media_assets_original_media_asset_id" not in existing_indexes:
        op.create_index("ix_media_assets_original_media_asset_id", "media_assets", ["original_media_asset_id"])

    if not sa.inspect(bind).has_table("media_asset_evidence"):
        op.create_table(
            "media_asset_evidence",
            sa.Column("media_asset_id", sa.String(length=36), sa.ForeignKey("media_assets.id", ondelete="RESTRICT"), primary_key=True),
            sa.Column("evidence_id", sa.String(length=36), sa.ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="supports"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("media_asset_evidence"):
        op.drop_table("media_asset_evidence")

    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("media_assets")}
    if "ix_media_assets_original_media_asset_id" in existing_indexes:
        op.drop_index("ix_media_assets_original_media_asset_id", table_name="media_assets")
    if "ix_media_assets_uploader_user_id" in existing_indexes:
        op.drop_index("ix_media_assets_uploader_user_id", table_name="media_assets")

    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("media_assets")}
    for column in reversed(MEDIA_COLUMNS):
        if column.name in existing_columns:
            op.drop_column("media_assets", column.name)

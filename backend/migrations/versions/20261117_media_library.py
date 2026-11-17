"""Add media library metadata and explicit MediaAsset ↔ Evidence links."""
from alembic import op
import sqlalchemy as sa

revision = "20261117_media_library"
down_revision = "20261112_password_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("media_assets", sa.Column("category", sa.String(length=32), nullable=False, server_default="reference_photo"))
    op.add_column("media_assets", sa.Column("angle", sa.String(length=32), nullable=True))
    op.add_column("media_assets", sa.Column("status", sa.String(length=24), nullable=False, server_default="unreviewed"))
    op.add_column("media_assets", sa.Column("rights_status", sa.String(length=32), nullable=False, server_default="unknown"))
    op.add_column("media_assets", sa.Column("rights_holder", sa.String(length=240), nullable=True))
    op.add_column("media_assets", sa.Column("rights_notes", sa.Text(), nullable=True))
    op.add_column("media_assets", sa.Column("contributor_name", sa.String(length=240), nullable=True))
    op.add_column("media_assets", sa.Column("photographer_name", sa.String(length=240), nullable=True))
    op.add_column("media_assets", sa.Column("uploader_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True))
    op.add_column("media_assets", sa.Column("original_media_asset_id", sa.String(length=36), nullable=True))
    op.add_column("media_assets", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("media_assets", sa.Column("height", sa.Integer(), nullable=True))
    op.add_column("media_assets", sa.Column("byte_size", sa.Integer(), nullable=True))
    op.add_column("media_assets", sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_media_assets_uploader_user_id", "media_assets", ["uploader_user_id"])
    op.create_index("ix_media_assets_original_media_asset_id", "media_assets", ["original_media_asset_id"])
    op.create_table(
        "media_asset_evidence",
        sa.Column("media_asset_id", sa.String(length=36), sa.ForeignKey("media_assets.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("evidence_id", sa.String(length=36), sa.ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="supports"),
    )


def downgrade():
    op.drop_table("media_asset_evidence")
    op.drop_index("ix_media_assets_original_media_asset_id", table_name="media_assets")
    op.drop_index("ix_media_assets_uploader_user_id", table_name="media_assets")
    for column in (
        "is_featured", "byte_size", "height", "width",
        "original_media_asset_id", "uploader_user_id",
        "photographer_name", "contributor_name", "rights_notes",
        "rights_holder", "rights_status", "status", "angle", "category",
    ):
        op.drop_column("media_assets", column)

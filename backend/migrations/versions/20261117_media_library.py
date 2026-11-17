"""Add media library metadata and explicit MediaAsset ↔ Evidence links."""
from alembic import op
import sqlalchemy as sa

revision = "20261117_media_library"
down_revision = "20261112_password_auth"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("media_assets") as batch:
        batch.add_column(sa.Column("category", sa.String(length=32), nullable=False, server_default="reference_photo"))
        batch.add_column(sa.Column("angle", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("status", sa.String(length=24), nullable=False, server_default="unreviewed"))
        batch.add_column(sa.Column("rights_status", sa.String(length=32), nullable=False, server_default="unknown"))
        batch.add_column(sa.Column("rights_holder", sa.String(length=240), nullable=True))
        batch.add_column(sa.Column("rights_notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("contributor_name", sa.String(length=240), nullable=True))
        batch.add_column(sa.Column("photographer_name", sa.String(length=240), nullable=True))
        batch.add_column(sa.Column("uploader_user_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("original_media_asset_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("width", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("height", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("byte_size", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key("fk_media_assets_uploader_user", "users", ["uploader_user_id"], ["id"], ondelete="RESTRICT")
        batch.create_check_constraint("ck_media_assets_category", "category IN ('reference_photo', 'evidence_photo', 'package_photo', 'physical_specimen', 'document', 'other')")
        batch.create_check_constraint("ck_media_assets_angle", "angle IS NULL OR angle IN ('front', 'rear', 'left', 'right', 'top', 'bottom', 'package_front', 'package_back', 'detail', 'other')")
        batch.create_check_constraint("ck_media_assets_status", "status IN ('unreviewed', 'approved', 'rejected', 'archived')")
        batch.create_check_constraint("ck_media_assets_rights_status", "rights_status IN ('unknown', 'permission_requested', 'permitted', 'restricted', 'denied')")
        batch.create_check_constraint("ck_media_assets_width_positive", "width IS NULL OR width > 0")
        batch.create_check_constraint("ck_media_assets_height_positive", "height IS NULL OR height > 0")
        batch.create_check_constraint("ck_media_assets_byte_size_nonnegative", "byte_size IS NULL OR byte_size >= 0")

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
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_constraint("ck_media_assets_byte_size_nonnegative", type_="check")
        batch.drop_constraint("ck_media_assets_height_positive", type_="check")
        batch.drop_constraint("ck_media_assets_width_positive", type_="check")
        batch.drop_constraint("ck_media_assets_rights_status", type_="check")
        batch.drop_constraint("ck_media_assets_status", type_="check")
        batch.drop_constraint("ck_media_assets_angle", type_="check")
        batch.drop_constraint("ck_media_assets_category", type_="check")
        batch.drop_constraint("fk_media_assets_uploader_user", type_="foreignkey")
        batch.drop_column("is_featured")
        batch.drop_column("byte_size")
        batch.drop_column("height")
        batch.drop_column("width")
        batch.drop_column("original_media_asset_id")
        batch.drop_column("uploader_user_id")
        batch.drop_column("photographer_name")
        batch.drop_column("contributor_name")
        batch.drop_column("rights_notes")
        batch.drop_column("rights_holder")
        batch.drop_column("rights_status")
        batch.drop_column("status")
        batch.drop_column("angle")
        batch.drop_column("category")

"""Store localized Casting descriptions for the supported catalog languages.

Legacy castings.description is intentionally retained and not copied: its
language is not reliably known, and damaged text must not be propagated.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261125_casting_localized_descriptions"
down_revision = "20261105_casting_grouping_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "casting_translations",
        sa.Column("casting_id", sa.String(length=36), nullable=False),
        sa.Column("language_code", sa.String(length=5), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "language_code IN ('en', 'ru', 'ja')",
            name="ck_casting_translations_language",
        ),
        sa.CheckConstraint(
            "length(trim(description)) > 0",
            name="ck_casting_translations_description_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["casting_id"], ["castings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("casting_id", "language_code"),
    )


def downgrade() -> None:
    op.drop_table("casting_translations")

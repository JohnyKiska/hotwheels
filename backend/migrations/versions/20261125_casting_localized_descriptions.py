"""Create the localized Casting description table safely on existing schemas."""
from alembic import op

revision = "20261125_casting_localized_descriptions"
down_revision = "20261105_casting_grouping_review"
branch_labels = None
depends_on = None

TABLES = ("casting_translations",)


def upgrade() -> None:
    # create_all is idempotent for a table that may already exist in a
    # database initialized from the complete current ORM metadata.
    from app import models  # noqa: F401
    from app.db import Base

    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=[Base.metadata.tables[name] for name in TABLES],
    )


def downgrade() -> None:
    from app.db import Base

    Base.metadata.drop_all(
        bind=op.get_bind(),
        tables=[Base.metadata.tables[name] for name in reversed(TABLES)],
    )

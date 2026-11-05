"""Add manufacturer, brand, and their catalog relationships."""

from alembic import op

revision = "20261029_manufacturer_brand"
down_revision = "20261029_packages"
branch_labels = None
depends_on = None

TABLES = (
    "manufacturers",
    "brands",
    "manufacturer_brands",
    "casting_brands",
    "release_brands",
    "evidence_manufacturers",
    "evidence_brands",
)


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in TABLES],
    )


def downgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in reversed(TABLES)],
    )

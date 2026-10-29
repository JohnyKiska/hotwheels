"""Add product lines and typed catalog-tree placements."""

from alembic import op

revision = "20261029_catalog_tree"
down_revision = "20261029_manufacturer_brand"
branch_labels = None
depends_on = None

TABLES = (
    "product_lines",
    "product_line_brands",
    "catalog_nodes",
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

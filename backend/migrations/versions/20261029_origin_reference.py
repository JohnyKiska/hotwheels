"""Add origin objects, optional variants, structured specifications, and evidence links."""

from alembic import op

revision = "20261029_origin_reference"
down_revision = "20261029_catalog_tree"
branch_labels = None
depends_on = None

TABLES = (
    "origin_objects",
    "origin_variants",
    "origin_specifications",
    "casting_origins",
    "evidence_origin_objects",
    "evidence_origin_variants",
    "evidence_origin_specifications",
    "evidence_casting_origins",
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

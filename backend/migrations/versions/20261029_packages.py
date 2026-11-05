"""Add package records, ordered contents, identifiers, and package evidence."""

from alembic import op

revision = "20261029_packages"
down_revision = "20261027_change_log_append_only"
branch_labels = None
depends_on = None

TABLES = (
    "packages",
    "package_releases",
    "package_identifiers",
    "evidence_packages",
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

"""Add short-lived OAuth authorization transactions."""
from alembic import op

revision = "20261112_oauth_requests"
down_revision = "20261112_email_outbox"
branch_labels = None
depends_on = None


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["oauth_authorization_requests"]],
    )


def downgrade():
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables["oauth_authorization_requests"]],
    )

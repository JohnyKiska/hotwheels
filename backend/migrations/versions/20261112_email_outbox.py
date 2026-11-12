"""Add encrypted transactional email outbox."""
from alembic import op

revision = "20261112_email_outbox"
down_revision = "20261112_account_security"
branch_labels = None
depends_on = None


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["outbound_emails"]],
    )


def downgrade():
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables["outbound_emails"]],
    )

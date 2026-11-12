"""Add password reset tokens and persistent authentication throttling."""
from alembic import op

revision = "20261112_password_auth"
down_revision = "20261112_oauth_requests"
branch_labels = None
depends_on = None


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[
            Base.metadata.tables["password_reset_tokens"],
            Base.metadata.tables["auth_rate_limit_buckets"],
        ],
    )


def downgrade():
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.drop_all(
        bind=bind,
        tables=[
            Base.metadata.tables["auth_rate_limit_buckets"],
            Base.metadata.tables["password_reset_tokens"],
        ],
    )

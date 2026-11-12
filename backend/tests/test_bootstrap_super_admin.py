import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db import Base
from app.bootstrap_super_admin import BootstrapError, bootstrap_super_admin
from app.models import AuditEvent, ExternalIdentity, Role, UserRole


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Role(code="super_admin", name="Super Admin"))
        db.commit()
        yield db
    engine.dispose()


def test_bootstrap_creates_active_super_admin_linked_by_numeric_github_id(session):
    user = bootstrap_super_admin(
        session,
        github_id="12345678",
        github_username="collector-admin",
    )
    session.commit()

    identity = session.scalar(
        select(ExternalIdentity).where(ExternalIdentity.user_id == user.id)
    )
    assignment = session.scalar(
        select(UserRole).where(UserRole.user_id == user.id)
    )
    audit = session.scalar(
        select(AuditEvent).where(AuditEvent.action == "account.super_admin.bootstrap")
    )

    assert user.status == "active"
    assert identity.provider == "github"
    assert identity.issuer == "https://github.com"
    assert identity.provider_subject == "12345678"
    assert assignment is not None
    assert audit.target_id == user.id


def test_bootstrap_refuses_second_super_admin(session):
    bootstrap_super_admin(session, github_id="12345678")
    session.commit()

    with pytest.raises(BootstrapError, match="assignment already exists"):
        bootstrap_super_admin(session, github_id="87654321")


def test_bootstrap_requires_numeric_github_id(session):
    with pytest.raises(BootstrapError, match="positive numeric"):
        bootstrap_super_admin(session, github_id="collector-admin")

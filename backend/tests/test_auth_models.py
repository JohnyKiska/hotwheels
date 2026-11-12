import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    EmailAddress,
    ExternalIdentity,
    PasswordCredential,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)


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
        yield db
    engine.dispose()


def test_user_can_have_multiple_login_identities(session):
    user = User(status="active")
    session.add(user)
    session.flush()
    session.add_all([
        ExternalIdentity(
            user_id=user.id, provider="github", issuer="https://github.com",
            provider_subject="12345",
        ),
        ExternalIdentity(
            user_id=user.id, provider="google", issuer="https://accounts.google.com",
            provider_subject="google-subject",
        ),
    ])
    session.commit()

    assert session.scalar(
        select(ExternalIdentity).where(ExternalIdentity.user_id == user.id)
    ) is not None


def test_external_identity_is_unique_by_issuer_and_subject(session):
    first = User(status="active")
    second = User(status="active")
    session.add_all([first, second])
    session.flush()
    session.add_all([
        ExternalIdentity(
            user_id=first.id, provider="github", issuer="https://github.com",
            provider_subject="same-subject",
        ),
        ExternalIdentity(
            user_id=second.id, provider="github", issuer="https://github.com",
            provider_subject="same-subject",
        ),
    ])
    with pytest.raises(IntegrityError):
        session.commit()


def test_same_subject_can_exist_under_different_issuers(session):
    user_a, user_b = User(status="active"), User(status="active")
    session.add_all([user_a, user_b])
    session.flush()
    session.add_all([
        ExternalIdentity(
            user_id=user_a.id, provider="google", issuer="issuer-a",
            provider_subject="subject",
        ),
        ExternalIdentity(
            user_id=user_b.id, provider="google", issuer="issuer-b",
            provider_subject="subject",
        ),
    ])
    session.commit()


def test_email_address_is_globally_unique_even_when_disabled(session):
    first, second = User(status="active"), User(status="active")
    session.add_all([first, second])
    session.flush()
    session.add(EmailAddress(
        user_id=first.id, email_normalized="person@example.com",
        email_display="Person@example.com", disabled_at=None,
    ))
    session.commit()
    session.add(EmailAddress(
        user_id=second.id, email_normalized="person@example.com",
        email_display="person@example.com",
    ))
    with pytest.raises(IntegrityError):
        session.commit()


def test_email_normalized_must_be_lowercase(session):
    user = User(status="active")
    session.add(user)
    session.flush()
    session.add(EmailAddress(
        user_id=user.id, email_normalized="Person@example.com",
        email_display="Person@example.com",
    ))
    with pytest.raises(IntegrityError):
        session.commit()


def test_one_password_credential_per_user(session):
    user = User(status="active")
    session.add(user)
    session.flush()
    session.add_all([
        PasswordCredential(user_id=user.id, password_hash="hash-one"),
        PasswordCredential(user_id=user.id, password_hash="hash-two"),
    ])
    with pytest.raises(IntegrityError):
        session.commit()


def test_role_permissions_and_user_role_foreign_keys(session):
    user = User(status="active")
    role = Role(code="editor", name="Editor")
    permission = Permission(code="catalog.update")
    session.add_all([user, role, permission])
    session.flush()
    session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    session.add(UserRole(user_id=user.id, role_id=role.id))
    session.commit()

    assert session.scalar(select(UserRole).where(UserRole.user_id == user.id)) is not None


def test_user_role_history_allows_regrant_after_revocation(session):
    user = User(status="active")
    role = Role(code="reviewer", name="Reviewer")
    session.add_all([user, role])
    session.flush()
    from datetime import datetime, timezone

    revoked_at = datetime.now(timezone.utc)
    session.add(UserRole(user_id=user.id, role_id=role.id, assigned_at=revoked_at, revoked_at=revoked_at))
    session.add(UserRole(user_id=user.id, role_id=role.id))
    session.commit()

    assignments = session.scalars(
        select(UserRole).where(UserRole.user_id == user.id)
    ).all()
    assert len(assignments) == 2


def test_user_status_is_constrained(session):
    session.add(User(status="administrator"))
    with pytest.raises(IntegrityError):
        session.commit()

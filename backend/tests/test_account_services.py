from datetime import timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    AuditEvent,
    EmailAddress,
    EmailVerificationToken,
    Invitation,
    Role,
    User,
    UserRole,
    UserSession,
)
from app.account_services import (
    AccountServiceError,
    accept_invitation,
    assign_role,
    authenticate_session,
    consume_email_verification,
    create_email_verification,
    create_invitation,
    create_session,
    create_user,
    revoke_role,
    revoke_session,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_session_token_is_returned_once_and_only_hash_is_stored(db):
    user = create_user(db, status="active")
    session, raw_token = create_session(db, user_id=user.id)

    assert raw_token
    assert session.token_hash != raw_token
    assert len(session.token_hash) == 64
    assert db.scalar(select(UserSession).where(
        UserSession.token_hash == raw_token
    )) is None
    authenticated = authenticate_session(db, raw_token)
    assert authenticated is not None
    assert authenticated[1].id == user.id


def test_revoked_session_cannot_authenticate(db):
    user = create_user(db, status="active")
    _, raw_token = create_session(db, user_id=user.id)

    assert revoke_session(db, raw_token, reason="logout") is True
    assert revoke_session(db, raw_token, reason="logout") is False
    assert authenticate_session(db, raw_token) is None


def test_session_creation_rejects_inactive_user_and_excessive_lifetime(db):
    user = create_user(db, status="pending")
    with pytest.raises(AccountServiceError, match="user_not_active"):
        create_session(db, user_id=user.id)

    active = create_user(db, status="active")
    with pytest.raises(AccountServiceError, match="invalid_session_lifetime"):
        create_session(db, user_id=active.id, lifetime=timedelta(days=91))


def test_role_assignment_is_idempotent_and_revocation_preserves_history(db):
    user = create_user(db, status="active")
    role = Role(code="editor", name="Editor")
    db.add(role)
    db.flush()

    first = assign_role(db, user_id=user.id, role_id=role.id)
    second = assign_role(db, user_id=user.id, role_id=role.id)
    assert first.id == second.id
    assert revoke_role(db, user_id=user.id, role_id=role.id) is True
    third = assign_role(db, user_id=user.id, role_id=role.id)
    assert third.id != first.id
    rows = db.scalars(select(UserRole).where(UserRole.user_id == user.id)).all()
    assert len(rows) == 2
    assert rows[0].revoked_at is not None


def test_super_admin_cannot_be_assigned_through_regular_role_service(db):
    user = create_user(db, status="active")
    role = Role(code="super_admin", name="Super Admin")
    db.add(role)
    db.flush()
    with pytest.raises(AccountServiceError, match="super_admin_requires_bootstrap"):
        assign_role(db, user_id=user.id, role_id=role.id)


def test_invitation_acceptance_creates_verified_user_and_assigns_role(db):
    inviter = create_user(db, status="active")
    role = Role(code="editor", name="Editor")
    db.add(role)
    db.flush()
    invitation, raw_token = create_invitation(
        db,
        email="Collector@Example.com",
        invited_by_user_id=inviter.id,
        role_id=role.id,
    )

    user, email = accept_invitation(db, raw_token, display_name="Collector")

    assert invitation.status == "accepted"
    assert user.status == "active"
    assert email.email_normalized == "collector@example.com"
    assert email.verified_at is not None
    assert db.scalar(select(UserRole).where(
        UserRole.user_id == user.id,
        UserRole.role_id == role.id,
        UserRole.revoked_at.is_(None),
    )) is not None
    with pytest.raises(AccountServiceError, match="invalid_invitation"):
        accept_invitation(db, raw_token)


def test_invitation_token_is_not_stored_and_super_admin_invite_is_blocked(db):
    inviter = create_user(db, status="active")
    role = Role(code="super_admin", name="Super Admin")
    db.add(role)
    db.flush()
    with pytest.raises(AccountServiceError, match="super_admin_cannot_be_invited"):
        create_invitation(
            db, email="root@example.com",
            invited_by_user_id=inviter.id, role_id=role.id,
        )

    invitation, raw_token = create_invitation(
        db, email="person@example.com", invited_by_user_id=inviter.id,
    )
    assert invitation.token_hash != raw_token
    assert len(invitation.token_hash) == 64


def test_email_verification_is_one_time_and_activates_pending_user(db):
    user = create_user(db, status="pending")
    email = EmailAddress(
        user_id=user.id,
        email_normalized="person@example.com",
        email_display="Person@example.com",
    )
    db.add(email)
    db.flush()

    token, raw_token = create_email_verification(db, email_address_id=email.id)
    assert token.token_hash != raw_token

    verified = consume_email_verification(db, raw_token)
    assert verified.verified_at is not None
    assert user.status == "active"
    with pytest.raises(AccountServiceError, match="invalid_verification_token"):
        consume_email_verification(db, raw_token)


def test_email_verification_rejects_expired_token(db):
    user = create_user(db, status="pending")
    email = EmailAddress(
        user_id=user.id,
        email_normalized="expired@example.com",
        email_display="expired@example.com",
    )
    db.add(email)
    db.flush()
    token, raw_token = create_email_verification(db, email_address_id=email.id)
    from datetime import datetime, timezone
    token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()

    with pytest.raises(AccountServiceError, match="verification_token_expired"):
        consume_email_verification(db, raw_token)


def test_account_services_write_audit_events_without_token_material(db):
    user = create_user(db, status="active")
    _, raw_token = create_session(db, user_id=user.id)
    events = db.scalars(select(AuditEvent)).all()

    assert any(event.action == "auth.session.created" for event in events)
    assert all(raw_token not in str(event.event_metadata) for event in events)

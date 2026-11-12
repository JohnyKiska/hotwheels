import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, delete, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    AuditEvent,
    EmailAddress,
    EmailVerificationToken,
    Invitation,
    Role,
    User,
    UserSession,
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


def test_session_stores_hash_and_can_be_revoked(db):
    user = User(status="active")
    now = datetime.now(timezone.utc)
    session = UserSession(
        user=user,
        token_hash="a" * 64,
        created_at=now,
        expires_at=now + timedelta(days=7),
        revoked_at=now + timedelta(hours=1),
        revoke_reason="user_logout",
    )
    db.add(session)
    db.commit()

    loaded = db.get(UserSession, session.id)
    assert loaded is not None
    assert loaded.token_hash == "a" * 64
    assert loaded.revoke_reason == "user_logout"


def test_session_rejects_expiry_before_creation(db):
    now = datetime.now(timezone.utc)
    db.add(UserSession(
        user=User(status="active"),
        token_hash="b" * 64,
        created_at=now,
        expires_at=now - timedelta(seconds=1),
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_session_token_hash_must_be_unique(db):
    now = datetime.now(timezone.utc)
    user = User(status="active")
    db.add_all([
        UserSession(user=user, token_hash="c" * 64, created_at=now,
                    expires_at=now + timedelta(days=1)),
        UserSession(user=user, token_hash="c" * 64, created_at=now,
                    expires_at=now + timedelta(days=2)),
    ])
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invitation_links_inviter_role_and_accepting_user(db):
    inviter = User(status="active")
    accepted_user = User(status="active")
    role = Role(code="editor", name="Editor")
    db.add_all([inviter, accepted_user, role])
    db.flush()
    invitation = Invitation(
        email_normalized="collector@example.com",
        token_hash="d" * 64,
        invited_by_user_id=inviter.id,
        role_id=role.id,
        status="accepted",
        expires_at=datetime.now(timezone.utc) + timedelta(days=2),
        accepted_by_user_id=accepted_user.id,
        accepted_at=datetime.now(timezone.utc),
    )
    db.add(invitation)
    db.commit()

    loaded = db.get(Invitation, invitation.id)
    assert loaded is not None
    assert loaded.role_id == role.id
    assert loaded.accepted_by_user_id == accepted_user.id


def test_invitation_rejects_accepted_status_without_acceptance_fields(db):
    inviter = User(status="active")
    db.add(inviter)
    db.flush()
    invitation = Invitation(
        email_normalized="collector@example.com",
        token_hash="e" * 64,
        invited_by_user_id=inviter.id,
        status="accepted",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.add(invitation)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invitation_email_must_be_normalized(db):
    inviter = User(status="active")
    db.add(inviter)
    db.flush()
    db.add(Invitation(
        email_normalized="Collector@Example.com",
        token_hash="f" * 64,
        invited_by_user_id=inviter.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_email_verification_token_is_one_time_and_hash_only(db):
    user = User(status="pending")
    email = EmailAddress(
        user=user,
        email_normalized="new@example.com",
        email_display="New@example.com",
    )
    db.add(email)
    db.flush()
    now = datetime.now(timezone.utc)
    token = EmailVerificationToken(
        email_address_id=email.id,
        token_hash="1" * 64,
        created_at=now,
        expires_at=now + timedelta(hours=1),
        consumed_at=now + timedelta(minutes=5),
    )
    db.add(token)
    db.commit()

    loaded = db.get(EmailVerificationToken, token.id)
    assert loaded is not None
    assert loaded.token_hash == "1" * 64
    assert loaded.consumed_at is not None
    assert not hasattr(loaded, "raw_token")


def test_email_verification_rejects_expiry_before_creation(db):
    user = User(status="pending")
    email = EmailAddress(
        user=user,
        email_normalized="expired@example.com",
        email_display="expired@example.com",
    )
    db.add(email)
    db.flush()
    now = datetime.now(timezone.utc)
    db.add(EmailVerificationToken(
        email_address_id=email.id,
        token_hash="2" * 64,
        created_at=now,
        expires_at=now - timedelta(seconds=1),
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_audit_event_captures_actor_action_target_and_request(db):
    actor = User(status="active")
    db.add(actor)
    db.flush()
    audit_event = AuditEvent(
        actor_user_id=actor.id,
        action="user.role.assigned",
        target_type="user",
        target_id="target-user-id",
        request_id="request-123",
        result="success",
        event_metadata={"role": "editor"},
    )
    db.add(audit_event)
    db.commit()

    loaded = db.get(AuditEvent, audit_event.id)
    assert loaded is not None
    assert loaded.actor_user_id == actor.id
    assert loaded.event_metadata == {"role": "editor"}


def test_audit_event_rejects_unknown_result(db):
    db.add(AuditEvent(action="auth.login", result="maybe"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_audit_events_are_append_only_after_migration(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    database_path = tmp_path / "account_audit.db"
    url = f"sqlite:///{database_path}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO audit_events
                    (id, action, result, created_at)
                VALUES ('audit-event-1', 'auth.login', 'success', CURRENT_TIMESTAMP)
            """))

        with pytest.raises(Exception, match="audit_events is append-only"):
            with engine.begin() as connection:
                connection.execute(text("""
                    UPDATE audit_events SET result = 'failure'
                    WHERE id = 'audit-event-1'
                """))

        with pytest.raises(Exception, match="audit_events is append-only"):
            with engine.begin() as connection:
                connection.execute(text("""
                    DELETE FROM audit_events WHERE id = 'audit-event-1'
                """))

        with engine.connect() as connection:
            assert connection.execute(text("""
                SELECT result FROM audit_events WHERE id = 'audit-event-1'
            """)).scalar_one() == "success"
    finally:
        engine.dispose()

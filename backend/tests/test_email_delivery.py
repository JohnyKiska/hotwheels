from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.email_delivery import (
    EmailOutboxError,
    dispatch_outbox_batch,
    queue_email,
)
from app.models import OutboundEmail


class FakeProvider:
    def __init__(self, failures=0):
        self.failures = failures
        self.messages = []

    def send_email(self, message):
        if self.failures:
            self.failures -= 1
            raise RuntimeError("provider unavailable")
        self.messages.append(message)


@pytest.fixture
def db_factory():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("HW_EMAIL_ENCRYPTION_KEY", key)
    return key


def test_outbox_encrypts_message_payload_and_is_idempotent(
    db_factory, encryption_key
):
    with db_factory() as db:
        row = queue_email(
            db,
            recipient="Person@Example.com",
            subject="Verify your email",
            text_body="Use this secret token: token-value-123",
            idempotency_key="verify:user-1:token-1",
        )
        db.flush()
        encrypted = row.encrypted_payload
        assert "token-value-123" not in encrypted
        assert "Verify your email" not in encrypted
        assert row.recipient_email == "person@example.com"

        again = queue_email(
            db,
            recipient="person@example.com",
            subject="A different subject is ignored for the same key",
            text_body="A different body",
            idempotency_key="verify:user-1:token-1",
        )
        assert again.id == row.id
        db.commit()

    with db_factory() as db:
        rows = db.scalars(select(OutboundEmail)).all()
        assert len(rows) == 1


def test_outbox_rejects_missing_encryption_key(db_factory, monkeypatch):
    monkeypatch.delenv("HW_EMAIL_ENCRYPTION_KEY", raising=False)
    with db_factory() as db:
        with pytest.raises(EmailOutboxError, match="email_encryption_key_not_configured"):
            queue_email(
                db,
                recipient="person@example.com",
                subject="Hello",
                text_body="Body",
                idempotency_key="key-1",
            )


def test_dispatch_sends_and_marks_outbox_item_sent(db_factory, encryption_key):
    with db_factory() as db:
        row = queue_email(
            db,
            recipient="person@example.com",
            subject="Welcome",
            text_body="Welcome to HW Catalog",
            html_body="<p>Welcome</p>",
            idempotency_key="welcome:user-1",
        )
        row_id = row.id
        db.commit()

    provider = FakeProvider()
    result = dispatch_outbox_batch(db_factory, provider)

    assert result == {"sent": 1, "retrying": 0, "failed": 0}
    assert len(provider.messages) == 1
    assert provider.messages[0].recipient == "person@example.com"
    assert provider.messages[0].subject == "Welcome"
    assert provider.messages[0].text_body == "Welcome to HW Catalog"
    assert provider.messages[0].html_body == "<p>Welcome</p>"
    assert provider.messages[0].idempotency_key == "welcome:user-1"

    with db_factory() as db:
        row = db.get(OutboundEmail, row_id)
        assert row.status == "sent"
        assert row.sent_at is not None
        assert row.locked_at is None


def test_dispatch_retries_with_backoff_then_marks_failed(db_factory, encryption_key):
    with db_factory() as db:
        row = queue_email(
            db,
            recipient="person@example.com",
            subject="Verify",
            text_body="Link",
            idempotency_key="verify:user-2",
        )
        row_id = row.id
        db.commit()

    now = datetime.now(timezone.utc)
    provider = FakeProvider(failures=2)

    first = dispatch_outbox_batch(db_factory, provider, now=now, max_attempts=2)
    assert first == {"sent": 0, "retrying": 1, "failed": 0}

    with db_factory() as db:
        row = db.get(OutboundEmail, row_id)
        assert row.status == "pending"
        assert row.attempt_count == 1
        assert row.available_at.replace(tzinfo=timezone.utc) > now
        assert "provider unavailable" not in (row.last_error or "")

    second = dispatch_outbox_batch(
        db_factory, provider, now=now + timedelta(minutes=3), max_attempts=2
    )
    assert second == {"sent": 0, "retrying": 0, "failed": 1}

    with db_factory() as db:
        row = db.get(OutboundEmail, row_id)
        assert row.status == "failed"
        assert row.attempt_count == 2


def test_dispatch_fails_closed_when_encryption_key_changes(db_factory, encryption_key, monkeypatch):
    with db_factory() as db:
        row = queue_email(
            db,
            recipient="person@example.com",
            subject="Verify",
            text_body="Sensitive link",
            idempotency_key="verify:user-3",
        )
        row_id = row.id
        db.commit()

    monkeypatch.setenv("HW_EMAIL_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    provider = FakeProvider()
    result = dispatch_outbox_batch(db_factory, provider)

    assert result == {"sent": 0, "retrying": 0, "failed": 1}
    assert provider.messages == []
    with db_factory() as db:
        row = db.get(OutboundEmail, row_id)
        assert row.status == "failed"
        assert row.last_error == "payload_decryption_failed"



def test_dispatch_does_not_claim_messages_when_encryption_key_is_missing(
    db_factory, encryption_key, monkeypatch
):
    with db_factory() as db:
        row = queue_email(
            db,
            recipient="person@example.com",
            subject="Verify",
            text_body="Sensitive link",
            idempotency_key="verify:user-4",
        )
        row_id = row.id
        db.commit()

    monkeypatch.delenv("HW_EMAIL_ENCRYPTION_KEY", raising=False)
    provider = FakeProvider()
    with pytest.raises(EmailOutboxError, match="email_encryption_key_not_configured"):
        dispatch_outbox_batch(db_factory, provider)

    with db_factory() as db:
        row = db.get(OutboundEmail, row_id)
        assert row.status == "pending"
        assert row.attempt_count == 0
    assert provider.messages == []

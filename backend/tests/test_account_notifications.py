from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.account_notifications import (
    create_email_verification_and_queue_email,
    create_invitation_and_queue_email,
)
from app.db import Base
from app.email_delivery import dispatch_outbox_batch
from app.models import EmailAddress, Invitation, OutboundEmail, User


class CaptureProvider:
    def __init__(self):
        self.messages = []

    def send_email(self, message):
        self.messages.append(message)


def make_factory():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_invitation_and_email_are_created_in_same_transaction(monkeypatch):
    monkeypatch.setenv("HW_EMAIL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("HW_FRONTEND_URL", "https://frontend.example.com")
    engine, factory = make_factory()
    try:
        with factory() as db:
            inviter = User(status="active", display_name="Admin")
            db.add(inviter)
            db.flush()
            invitation = create_invitation_and_queue_email(
                db,
                email="Collector@Example.com",
                invited_by_user_id=inviter.id,
                public_base_url="https://catalog.example.com",
                recipient_name="Collector",
            )
            queued = db.scalar(select(OutboundEmail))
            assert invitation.status == "pending"
            assert queued is not None
            assert queued.recipient_email == "collector@example.com"
            assert queued.status == "pending"
            assert "token=" not in queued.encrypted_payload
            db.commit()

        provider = CaptureProvider()
        result = dispatch_outbox_batch(factory, provider)
        assert result["sent"] == 1
        assert len(provider.messages) == 1
        assert "Принять приглашение" in provider.messages[0].html_body
        assert "https://frontend.example.com/login.html?invite=" in provider.messages[0].text_body
        assert "login.html?invite=" in provider.messages[0].text_body
    finally:
        engine.dispose()


def test_email_verification_and_outbox_are_created_together(monkeypatch):
    monkeypatch.setenv("HW_EMAIL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    engine, factory = make_factory()
    try:
        with factory() as db:
            user = User(status="pending")
            db.add(user)
            db.flush()
            email = EmailAddress(
                user_id=user.id,
                email_normalized="person@example.com",
                email_display="Person@example.com",
            )
            db.add(email)
            db.flush()

            result_email = create_email_verification_and_queue_email(
                db,
                email_address_id=email.id,
                public_base_url="https://catalog.example.com/",
            )
            queued = db.scalar(select(OutboundEmail))
            assert result_email.id == email.id
            assert queued is not None
            assert queued.recipient_email == email.email_normalized
            assert "token=" not in queued.encrypted_payload
            db.commit()

        provider = CaptureProvider()
        result = dispatch_outbox_batch(factory, provider)
        assert result["sent"] == 1
        assert "Подтвердить email" in provider.messages[0].html_body
        assert "https://frontend.example.com/login.html?verify=" in provider.messages[0].text_body
        assert "login.html?verify=" in provider.messages[0].text_body
    finally:
        engine.dispose()

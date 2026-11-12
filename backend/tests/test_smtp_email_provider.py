from email.message import EmailMessage as MIMEEmailMessage

import pytest

from app.email_delivery import EmailMessage, EmailOutboxError
from app.smtp_email_provider import SMTPEmailProvider


def test_smtp_provider_builds_multipart_message(monkeypatch):
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            captured["connection"] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            captured["ehlo"] = captured.get("ehlo", 0) + 1

        def starttls(self, context):
            captured["tls"] = context

        def login(self, username, password):
            captured["login"] = (username, password)

        def send_message(self, message):
            captured["message"] = message

    monkeypatch.setattr("app.smtp_email_provider.smtplib.SMTP", FakeSMTP)
    provider = SMTPEmailProvider(
        host="smtp.example.com",
        port=587,
        from_email="catalog@example.com",
        from_name="HW Catalog",
        username="mailer",
        password="secret",
        security="starttls",
    )
    provider.send_email(EmailMessage(
        recipient="person@example.com",
        subject="Welcome",
        text_body="Hello",
        html_body="<p>Hello</p>",
        idempotency_key="invite:123",
    ))

    assert captured["connection"] == ("smtp.example.com", 587, 20)
    assert captured["login"] == ("mailer", "secret")
    assert captured["ehlo"] == 2
    mime = captured["message"]
    assert isinstance(mime, MIMEEmailMessage)
    assert mime["To"] == "person@example.com"
    assert mime["Subject"] == "Welcome"
    assert mime["X-HW-Idempotency-Key"] == "invite:123"
    assert mime.get_payload()[0].get_content().strip() == "Hello"
    assert mime.get_payload()[1].get_content_type() == "text/html"


def test_smtp_provider_ssl_mode(monkeypatch):
    captured = {}

    class FakeSMTPSSL:
        def __init__(self, host, port, timeout, context):
            captured["connection"] = (host, port, timeout)
            captured["context"] = context

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send_message(self, message):
            captured["message"] = message

    monkeypatch.setattr("app.smtp_email_provider.smtplib.SMTP_SSL", FakeSMTPSSL)
    provider = SMTPEmailProvider(
        host="smtp.example.com",
        port=465,
        from_email="catalog@example.com",
        security="ssl",
    )
    provider.send_email(EmailMessage(
        recipient="person@example.com",
        subject="Hi",
        text_body="Hello",
        html_body=None,
        idempotency_key="key-1",
    ))
    assert captured["connection"] == ("smtp.example.com", 465, 20)


@pytest.mark.parametrize("kwargs", [
    {"host": "smtp.example.com\r\nBcc:bad@example.com", "port": 587,
     "from_email": "catalog@example.com"},
    {"host": "smtp.example.com", "port": 70000,
     "from_email": "catalog@example.com"},
    {"host": "smtp.example.com", "port": 587,
     "from_email": "not-an-email"},
    {"host": "smtp.example.com", "port": 587,
     "from_email": "catalog@example.com", "username": "mailer"},
    {"host": "smtp.example.com", "port": 587,
     "from_email": "catalog@example.com", "security": "plain-text"},
])
def test_smtp_provider_rejects_invalid_configuration(kwargs):
    with pytest.raises(EmailOutboxError):
        SMTPEmailProvider(**kwargs)


def test_smtp_provider_requires_env_configuration(monkeypatch):
    monkeypatch.delenv("HW_SMTP_HOST", raising=False)
    with pytest.raises(EmailOutboxError, match="hw_smtp_host_not_configured"):
        SMTPEmailProvider.from_env()


def test_smtp_provider_loads_environment(monkeypatch):
    monkeypatch.setenv("HW_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("HW_SMTP_FROM_EMAIL", "catalog@example.com")
    monkeypatch.setenv("HW_SMTP_SECURITY", "ssl")
    monkeypatch.setenv("HW_SMTP_PORT", "465")
    provider = SMTPEmailProvider.from_env()
    assert provider.host == "smtp.example.com"
    assert provider.port == 465
    assert provider.security == "ssl"

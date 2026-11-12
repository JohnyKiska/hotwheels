"""SMTP adapter for the provider-neutral transactional email outbox."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage as MIMEEmailMessage
from email.utils import formataddr, parseaddr

from .email_delivery import EmailMessage, EmailOutboxError


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise EmailOutboxError(f"{name.lower()}_not_configured")
    return value


def _safe_header(value: str, setting: str) -> str:
    if not value or "\r" in value or "\n" in value:
        raise EmailOutboxError(f"invalid_{setting.lower()}")
    return value


def _validated_address(value: str, setting: str) -> str:
    _safe_header(value, setting)
    _name, address = parseaddr(value)
    if not address or "@" not in address or address.startswith("@") or address.endswith("@"):
        raise EmailOutboxError(f"invalid_{setting.lower()}")
    return address


class SMTPEmailProvider:
    """Sends email through SMTP or SMTP-over-TLS.

    SMTP has no portable exactly-once guarantee. The idempotency key is
    attached as a diagnostic header; the outbox lease/retry policy remains
    at-least-once if a connection fails after the server accepted a message.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_email: str,
        from_name: str = "HW Catalog",
        username: str | None = None,
        password: str | None = None,
        security: str = "starttls",
        timeout: float = 20,
    ) -> None:
        self.host = _safe_header(host.strip(), "SMTP_HOST")
        if not self.host or port < 1 or port > 65535:
            raise EmailOutboxError("invalid_smtp_server")
        self.port = port
        self.from_email = _validated_address(from_email, "SMTP_FROM_EMAIL")
        self.from_name = _safe_header(from_name.strip(), "SMTP_FROM_NAME")
        if bool(username) != bool(password):
            raise EmailOutboxError("smtp_username_and_password_must_be_set_together")
        if security not in {"starttls", "ssl", "none"}:
            raise EmailOutboxError("invalid_smtp_security_mode")
        self.username = username
        self.password = password
        self.security = security
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "SMTPEmailProvider":
        try:
            port = int(os.environ.get("HW_SMTP_PORT", "587"))
            timeout = float(os.environ.get("HW_SMTP_TIMEOUT", "20"))
        except ValueError as exc:
            raise EmailOutboxError("invalid_smtp_numeric_setting") from exc
        security = os.environ.get("HW_SMTP_SECURITY", "starttls").strip().lower()
        username = os.environ.get("HW_SMTP_USERNAME") or None
        password = os.environ.get("HW_SMTP_PASSWORD") or None
        return cls(
            host=_required("HW_SMTP_HOST"),
            port=port,
            from_email=_required("HW_SMTP_FROM_EMAIL"),
            from_name=os.environ.get("HW_SMTP_FROM_NAME", "HW Catalog"),
            username=username,
            password=password,
            security=security,
            timeout=timeout,
        )

    def send_email(self, message: EmailMessage) -> None:
        mime = MIMEEmailMessage()
        mime["Subject"] = _safe_header(message.subject, "email_subject")
        mime["From"] = formataddr((self.from_name, self.from_email))
        mime["To"] = _validated_address(message.recipient, "email_recipient")
        mime["X-HW-Idempotency-Key"] = _safe_header(
            message.idempotency_key, "idempotency_key"
        )
        mime.set_content(message.text_body)
        if message.html_body is not None:
            mime.add_alternative(message.html_body, subtype="html")

        context = ssl.create_default_context()
        if self.security == "ssl":
            with smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=context
            ) as server:
                self._deliver(server, mime)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
                server.ehlo()
                if self.security == "starttls":
                    server.starttls(context=context)
                    server.ehlo()
                self._deliver(server, mime)

    def _deliver(self, server, mime: MIMEEmailMessage) -> None:
        if self.username is not None:
            server.login(self.username, self.password)
        server.send_message(mime)

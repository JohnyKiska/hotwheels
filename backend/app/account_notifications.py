"""Account invitation and email-verification message composition.

Token-bearing URLs are encrypted by the outbox before they reach the database.
These functions share the caller's transaction with account token creation.
"""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from sqlalchemy.orm import Session

from .account_services import (
    create_email_verification,
    create_invitation,
)
from .email_delivery import queue_email
from .models import EmailAddress, Invitation


def _base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    if not (base.startswith("https://") or base.startswith("http://localhost")):
        raise ValueError("public_base_url_must_use_https")
    return base


def create_invitation_and_queue_email(
    db: Session,
    *,
    email: str,
    invited_by_user_id: str,
    public_base_url: str,
    role_id: str | None = None,
    recipient_name: str | None = None,
) -> Invitation:
    invitation, raw_token = create_invitation(
        db,
        email=email,
        invited_by_user_id=invited_by_user_id,
        role_id=role_id,
    )
    link = (
        f"{_base_url(public_base_url)}/account/accept-invitation"
        f"?token={quote(raw_token, safe='')}"
    )
    greeting = f"Здравствуйте, {recipient_name}!" if recipient_name else "Здравствуйте!"
    subject = "Приглашение в HW Catalog"
    text_body = (
        f"{greeting}\n\n"
        "Вас пригласили присоединиться к HW Catalog. "
        f"Чтобы принять приглашение, откройте ссылку: {link}\n\n"
        "Ссылка одноразовая и действует 7 дней. Если вы не ожидали приглашение, "
        "просто проигнорируйте это письмо."
    )
    html_body = (
        f"<p>{escape(greeting)}</p>"
        "<p>Вас пригласили присоединиться к HW Catalog.</p>"
        f'<p><a href="{escape(link, quote=True)}">Принять приглашение</a></p>'
        "<p>Ссылка одноразовая и действует 7 дней. "
        "Если вы не ожидали приглашение, просто проигнорируйте это письмо.</p>"
    )
    queue_email(
        db,
        recipient=invitation.email_normalized,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        idempotency_key=f"account-invitation:{invitation.id}",
    )
    return invitation


def create_email_verification_and_queue_email(
    db: Session,
    *,
    email_address_id: str,
    public_base_url: str,
) -> EmailAddress:
    email_address = db.get(EmailAddress, email_address_id)
    if email_address is None or email_address.disabled_at is not None:
        raise ValueError("email_unavailable")
    token, raw_token = create_email_verification(
        db,
        email_address_id=email_address_id,
    )
    link = (
        f"{_base_url(public_base_url)}/account/verify-email"
        f"?token={quote(raw_token, safe='')}"
    )
    subject = "Подтвердите адрес электронной почты HW Catalog"
    text_body = (
        "Чтобы подтвердить адрес электронной почты, откройте ссылку: "
        f"{link}\n\nСсылка действует 24 часа. Если вы не запрашивали "
        "подтверждение, проигнорируйте это письмо."
    )
    html_body = (
        "<p>Чтобы подтвердить адрес электронной почты, перейдите по ссылке:</p>"
        f'<p><a href="{escape(link, quote=True)}">Подтвердить email</a></p>'
        "<p>Ссылка действует 24 часа. Если вы не запрашивали подтверждение, "
        "проигнорируйте это письмо.</p>"
    )
    queue_email(
        db,
        recipient=email_address.email_normalized,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        idempotency_key=f"email-verification:{token.id}",
    )
    return email_address

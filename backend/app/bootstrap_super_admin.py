"""One-time, operator-invoked bootstrap for the first Super Admin.

This command deliberately is not called during application startup. The operator
must supply the immutable numeric GitHub account ID after verifying it out of band.
"""
from __future__ import annotations

import os
import re
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import AuditEvent, ExternalIdentity, Role, User, UserRole, utc_now


GITHUB_ISSUER = "https://github.com"


class BootstrapError(RuntimeError):
    pass


def bootstrap_super_admin(
    session: Session,
    *,
    github_id: str,
    github_username: str | None = None,
) -> User:
    """Create the first active Super Admin and bind its GitHub numeric ID."""
    subject = str(github_id).strip()
    if not re.fullmatch(r"[1-9][0-9]{0,19}", subject):
        raise BootstrapError("GitHub ID must be a positive numeric account ID.")

    now = utc_now()
    existing_admin = session.scalar(
        select(UserRole.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            Role.code == "super_admin",
            UserRole.revoked_at.is_(None),
            (UserRole.expires_at.is_(None)) | (UserRole.expires_at > now),
        )
        .limit(1)
    )
    if existing_admin is not None:
        raise BootstrapError("A Super Admin is already assigned; bootstrap is one-time.")

    existing_identity = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == GITHUB_ISSUER,
            ExternalIdentity.provider_subject == subject,
        )
    )
    if existing_identity is not None:
        raise BootstrapError("This GitHub identity is already linked to an HW Catalog account.")

    role = session.scalar(select(Role).where(Role.code == "super_admin"))
    if role is None:
        raise BootstrapError("The super_admin role is missing; run database migrations first.")

    user = User(status="active", display_name=(github_username or None))
    session.add(user)
    session.flush()

    session.add(ExternalIdentity(
        user_id=user.id,
        provider="github",
        issuer=GITHUB_ISSUER,
        provider_subject=subject,
        provider_username=github_username or None,
    ))
    session.add(UserRole(
        user_id=user.id,
        role_id=role.id,
        assigned_by_user_id=None,
        assigned_at=now,
    ))
    session.add(AuditEvent(
        actor_user_id=None,
        action="account.super_admin.bootstrap",
        target_type="user",
        target_id=user.id,
        result="success",
        event_metadata={"provider": "github"},
    ))
    session.flush()
    return user


def main() -> int:
    github_id = os.environ.get("HW_BOOTSTRAP_GITHUB_ID", "").strip()
    github_username = os.environ.get("HW_BOOTSTRAP_GITHUB_USERNAME", "").strip() or None
    if not github_id:
        print("Set HW_BOOTSTRAP_GITHUB_ID to the verified numeric GitHub account ID.", file=sys.stderr)
        return 2

    with SessionLocal() as session:
        try:
            user = bootstrap_super_admin(
                session,
                github_id=github_id,
                github_username=github_username,
            )
            session.commit()
        except BootstrapError as exc:
            session.rollback()
            print(f"Bootstrap refused: {exc}", file=sys.stderr)
            return 1
        except Exception:
            session.rollback()
            raise

    print(f"Created first Super Admin account {user.id} linked to GitHub ID {github_id}.")
    print("The user can now sign in through GitHub OAuth. No password or session was created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

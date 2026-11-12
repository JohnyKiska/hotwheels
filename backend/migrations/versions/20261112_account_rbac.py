"""Add user identities and role-based access control foundation.

This migration intentionally does not create sessions, invitations, or audit
records; those are separate implementation steps.
"""
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "20261112_account_rbac"
down_revision = "20261104_conflict_releases"
branch_labels = None
depends_on = None

TABLES = (
    "users",
    "external_identities",
    "email_addresses",
    "password_credentials",
    "roles",
    "permissions",
    "role_permissions",
    "user_roles",
)

ROLES = (
    ("super_admin", "Super Admin", "Full system access."),
    ("admin", "Administrator", "Catalog and user administration."),
    ("editor", "Editor", "Create and edit catalog records."),
    ("reviewer", "Reviewer", "Review catalog records and changes."),
    ("viewer", "Viewer", "Read-only catalog access."),
)

PERMISSIONS = (
    ("catalog.read", "Read catalog records."),
    ("catalog.create", "Create catalog records."),
    ("catalog.update", "Update catalog records."),
    ("catalog.delete", "Delete catalog records."),
    ("catalog.review", "Review catalog records and changes."),
    ("users.read", "Read user accounts."),
    ("users.manage", "Manage user accounts."),
    ("roles.assign", "Assign and revoke roles."),
    ("billing.manage", "Manage subscriptions and entitlements."),
    ("settings.manage", "Manage system settings."),
)

ROLE_PERMISSION_CODES = {
    "super_admin": tuple(code for code, _description in PERMISSIONS),
    "admin": (
        "catalog.read", "catalog.create", "catalog.update", "catalog.delete",
        "catalog.review", "users.read", "users.manage", "roles.assign",
        "billing.manage",
    ),
    "editor": ("catalog.read", "catalog.create", "catalog.update"),
    "reviewer": ("catalog.read", "catalog.review"),
    "viewer": ("catalog.read",),
}


def stable_id(kind, code):
    return str(uuid5(NAMESPACE_URL, f"hw-catalog:{kind}:{code}"))


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in TABLES],
    )

    roles = sa.table(
        "roles",
        sa.column("id", sa.String(36)),
        sa.column("code", sa.String(60)),
        sa.column("name", sa.String(120)),
        sa.column("description", sa.Text()),
        sa.column("is_system", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String(36)),
        sa.column("code", sa.String(100)),
        sa.column("description", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String(36)),
        sa.column("permission_id", sa.String(36)),
    )

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    existing_roles = dict(bind.execute(sa.select(roles.c.code, roles.c.id)).all())
    for code, name, description in ROLES:
        if code not in existing_roles:
            role_id = stable_id("role", code)
            bind.execute(roles.insert().values(
                id=role_id, code=code, name=name, description=description,
                is_system=True, created_at=now, updated_at=now,
            ))
            existing_roles[code] = role_id

    existing_permissions = dict(
        bind.execute(sa.select(permissions.c.code, permissions.c.id)).all()
    )
    for code, description in PERMISSIONS:
        if code not in existing_permissions:
            permission_id = stable_id("permission", code)
            bind.execute(permissions.insert().values(
                id=permission_id, code=code, description=description,
                created_at=now, updated_at=now,
            ))
            existing_permissions[code] = permission_id

    existing_pairs = set(bind.execute(
        sa.select(role_permissions.c.role_id, role_permissions.c.permission_id)
    ).all())
    for role_code, permission_codes in ROLE_PERMISSION_CODES.items():
        role_id = existing_roles[role_code]
        for permission_code in permission_codes:
            pair = (role_id, existing_permissions[permission_code])
            if pair not in existing_pairs:
                bind.execute(role_permissions.insert().values(
                    role_id=pair[0], permission_id=pair[1]
                ))


def downgrade():
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in reversed(TABLES)],
    )

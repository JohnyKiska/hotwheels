"""Add typed catalog identifiers and entity assignments.

Identifier values may be assigned to multiple entities; this is intentional so
ambiguous SKU/UPC observations can be reviewed rather than discarded.
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "20261027_catalog_identifiers"
down_revision = "20261026_evidence_layer"
branch_labels = None
depends_on = None

TABLES = (
    "casting_variant_identifiers",
    "casting_identifiers",
    "release_identifiers",
    "catalog_identifiers",
    "identifier_types",
)

IDENTIFIER_TYPES = (
    ("idtype-catalog-number", "catalog_number", "Catalog number"),
    ("idtype-mattel-product-number", "mattel_product_number", "Mattel product number"),
    ("idtype-sku", "sku", "SKU"),
    ("idtype-upc", "upc", "UPC"),
    ("idtype-ean", "ean", "EAN"),
    ("idtype-assortment-number", "assortment_number", "Assortment number"),
    ("idtype-series-number", "series_number", "Series number"),
    ("idtype-external-id", "external_id", "External source ID"),
    ("idtype-other", "other", "Other identifier"),
)


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in TABLES],
    )

    identifier_types = sa.table(
        "identifier_types",
        sa.column("id", sa.String(length=36)),
        sa.column("code", sa.String(length=60)),
        sa.column("label", sa.String(length=120)),
        sa.column("is_globally_unique", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    existing_codes = set(
        bind.execute(sa.select(identifier_types.c.code)).scalars().all()
    )
    now = datetime.now(timezone.utc)
    missing_rows = [
        {
            "id": identifier_id,
            "code": code,
            "label": label,
            "is_globally_unique": False,
            "created_at": now,
            "updated_at": now,
        }
        for identifier_id, code, label in IDENTIFIER_TYPES
        if code not in existing_codes
    ]
    if missing_rows:
        op.bulk_insert(identifier_types, missing_rows)


def downgrade():
    from app.db import Base

    bind = op.get_bind()
    codes = tuple(code for _identifier_id, code, _label in IDENTIFIER_TYPES)
    seeded_ids = tuple(identifier_id for identifier_id, _code, _label in IDENTIFIER_TYPES)
    bind.execute(
        sa.delete(Base.metadata.tables["identifier_types"]).where(
            Base.metadata.tables["identifier_types"].c.id.in_(seeded_ids)
        )
    )
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in TABLES],
    )

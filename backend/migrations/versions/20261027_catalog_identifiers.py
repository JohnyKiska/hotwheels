"""Add typed catalog identifiers and entity assignments.

Identifier values may be assigned to multiple entities; this is intentional so
ambiguous SKU/UPC observations can be reviewed rather than discarded.
"""
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


def upgrade():
    from app import models  # noqa: F401
    from app.db import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[name] for name in TABLES])
    # Seed the extensible identifier namespaces; none is globally unique by default.
    op.execute("""
        INSERT INTO identifier_types (id, code, label, is_globally_unique, created_at, updated_at)
        VALUES
        ('idtype-catalog-number', 'catalog_number', 'Catalog number', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('idtype-mattel-product-number', 'mattel_product_number', 'Mattel product number', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('idtype-sku', 'sku', 'SKU', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('idtype-upc', 'upc', 'UPC', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('idtype-ean', 'ean', 'EAN', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('idtype-assortment-number', 'assortment_number', 'Assortment number', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('idtype-series-number', 'series_number', 'Series number', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('idtype-external-id', 'external_id', 'External source ID', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('idtype-other', 'other', 'Other identifier', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)


def downgrade():
    from app.db import Base
    bind = op.get_bind()
    op.execute("DELETE FROM identifier_types WHERE code IN ('catalog_number','mattel_product_number','sku','upc','ean','assortment_number','series_number','external_id','other')")
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[name] for name in TABLES[:-1]] + [Base.metadata.tables[TABLES[-1]]])

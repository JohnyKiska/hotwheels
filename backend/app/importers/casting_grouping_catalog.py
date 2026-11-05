"""Read-only adapter from catalog rows to Casting grouping preview records."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Casting,
    CatalogIdentifier,
    Evidence,
    EvidenceRelease,
    IdentifierType,
    Release,
    ReleaseIdentifier,
)


def build_casting_grouping_catalog_records(
    session: Session,
    *,
    product_line: str,
    catalog_year: int | None = None,
) -> list[dict]:
    """Snapshot Releases, SKU identifiers and linked Col.# evidence using SELECTs only.

    Product line is intentionally supplied by the caller because it is not a
    canonical field on Release and must never be guessed from names or SKUs.
    """
    clean_product_line = " ".join(product_line.split())
    if not clean_product_line:
        raise ValueError("product_line must not be empty")

    release_query = (
        select(Release, Casting.name)
        .join(Casting, Casting.id == Release.casting_id)
        .order_by(Release.id)
    )
    if catalog_year is not None:
        release_query = release_query.where(Release.catalog_year == catalog_year)

    releases = session.execute(release_query).all()
    if not releases:
        return []

    release_ids = [release.id for release, _casting_name in releases]

    evidence_rows = session.execute(
        select(
            EvidenceRelease.release_id,
            Evidence.observed_value,
            Evidence.source_record_id,
            Evidence.attribute_name,
        )
        .join(Evidence, Evidence.id == EvidenceRelease.evidence_id)
        .where(
            EvidenceRelease.release_id.in_(release_ids),
            Evidence.attribute_name == "collector_number",
            Evidence.review_status != "rejected",
        )
        .order_by(
            EvidenceRelease.release_id,
            Evidence.source_record_id,
            Evidence.id,
        )
    ).all()

    claims_by_release: dict[str, list[dict]] = defaultdict(list)
    source_ids_by_release: dict[str, set[str]] = defaultdict(set)
    for release_id, value, source_record_id, attribute_name in evidence_rows:
        claims_by_release[release_id].append({
            "value": value,
            "source_record_id": source_record_id,
            "source_field": attribute_name,
        })
        source_ids_by_release[release_id].add(source_record_id)

    sku_rows = session.execute(
        select(ReleaseIdentifier.release_id, CatalogIdentifier.value)
        .join(
            CatalogIdentifier,
            CatalogIdentifier.id == ReleaseIdentifier.identifier_id,
        )
        .join(
            IdentifierType,
            IdentifierType.id == CatalogIdentifier.identifier_type_id,
        )
        .where(
            ReleaseIdentifier.release_id.in_(release_ids),
            IdentifierType.code == "sku",
        )
        .order_by(ReleaseIdentifier.release_id, CatalogIdentifier.value)
    ).all()
    skus_by_release: dict[str, list[str]] = defaultdict(list)
    for release_id, value in sku_rows:
        skus_by_release[release_id].append(value)

    records = []
    for release, casting_name in releases:
        records.append({
            "record_id": release.id,
            "release_id": release.id,
            "product_line": clean_product_line,
            "catalog_year": release.catalog_year,
            "collector_number_claims": claims_by_release[release.id],
            "sku": skus_by_release[release.id],
            "model_name": release.name or casting_name,
            "existing_casting_id": release.casting_id,
            "source_record_ids": sorted(source_ids_by_release[release.id]),
        })
    return records

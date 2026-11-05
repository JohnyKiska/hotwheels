"""Read-only adapter from catalog rows to Casting grouping preview records."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..models import (
    Casting, CatalogIdentifier, Evidence, EvidenceRelease,
    IdentifierType, Release, ReleaseIdentifier,
)


def build_casting_grouping_catalog_records(
    session: Session, *, product_line: str, catalog_year: int | None = None,
) -> list[dict]:
    """Snapshot only Releases inside the requested product-line tree branch.

    Product-line membership is derived from catalog_nodes parent-child links.
    The caller-supplied name is a selector, never a classification value.
    """
    clean_product_line = " ".join(product_line.split())
    if not clean_product_line:
        raise ValueError("product_line must not be empty")

    line_rows = session.execute(
        text(
            """
            SELECT cn.id, pl.name
            FROM catalog_nodes AS cn
            JOIN product_lines AS pl ON pl.id = cn.product_line_id
            WHERE cn.node_type = 'product_line'
              AND lower(trim(pl.name)) = lower(:product_line)
            ORDER BY cn.id
            """
        ),
        {"product_line": clean_product_line},
    ).all()
    if not line_rows:
        raise ValueError(f"Unknown product line: {clean_product_line}")
    if len(line_rows) > 1:
        raise ValueError(f"Ambiguous product line name: {clean_product_line}")

    line_node_id, canonical_product_line = line_rows[0]
    query = text(
        """
        WITH RECURSIVE line_tree(id, node_type, release_id) AS (
            SELECT id, node_type, release_id
            FROM catalog_nodes
            WHERE id = :line_node_id
            UNION
            SELECT child.id, child.node_type, child.release_id
            FROM catalog_nodes AS child
            JOIN line_tree AS parent ON child.parent_id = parent.id
        )
        SELECT DISTINCT r.id, c.name, r.catalog_year, r.casting_id
        FROM line_tree AS tree
        JOIN releases AS r
          ON tree.node_type = 'release' AND tree.release_id = r.id
        JOIN castings AS c ON c.id = r.casting_id
        WHERE (:catalog_year IS NULL OR r.catalog_year = :catalog_year)
        ORDER BY r.id
        """
    )
    releases = session.execute(
        query,
        {"line_node_id": line_node_id, "catalog_year": catalog_year},
    ).all()
    if not releases:
        return []

    release_ids = [release_id for release_id, _name, _year, _casting_id in releases]
    evidence_rows = session.execute(
        select(EvidenceRelease.release_id, Evidence.observed_value,
               Evidence.source_record_id, Evidence.attribute_name)
        .join(Evidence, Evidence.id == EvidenceRelease.evidence_id)
        .where(
            EvidenceRelease.release_id.in_(release_ids),
            Evidence.attribute_name == "collector_number",
            Evidence.review_status != "rejected",
        )
        .order_by(EvidenceRelease.release_id, Evidence.source_record_id, Evidence.id)
    ).all()
    claims_by_release: dict[str, list[dict]] = defaultdict(list)
    sources_by_release: dict[str, set[str]] = defaultdict(set)
    for release_id, value, source_id, attribute in evidence_rows:
        claims_by_release[release_id].append({
            "value": value, "source_record_id": source_id, "source_field": attribute,
        })
        sources_by_release[release_id].add(source_id)

    evidence_status_rows = session.execute(
        select(EvidenceRelease.release_id, Evidence.review_status, func.count())
        .join(Evidence, Evidence.id == EvidenceRelease.evidence_id)
        .where(EvidenceRelease.release_id.in_(release_ids))
        .group_by(EvidenceRelease.release_id, Evidence.review_status)
    ).all()
    evidence_status_by_release: dict[str, dict[str, int]] = defaultdict(dict)
    for release_id, review_status, count in evidence_status_rows:
        evidence_status_by_release[release_id][review_status or "unset"] = int(count)

    sku_rows = session.execute(
        select(ReleaseIdentifier.release_id, CatalogIdentifier.value)
        .join(CatalogIdentifier, CatalogIdentifier.id == ReleaseIdentifier.identifier_id)
        .join(IdentifierType, IdentifierType.id == CatalogIdentifier.identifier_type_id)
        .where(ReleaseIdentifier.release_id.in_(release_ids), IdentifierType.code == "sku")
        .order_by(ReleaseIdentifier.release_id, CatalogIdentifier.value)
    ).all()
    skus_by_release: dict[str, list[str]] = defaultdict(list)
    for release_id, value in sku_rows:
        skus_by_release[release_id].append(value)

    return [{
        "record_id": release_id,
        "release_id": release_id,
        "product_line": canonical_product_line,
        "catalog_year": release_year,
        "collector_number_claims": claims_by_release[release_id],
        "sku": skus_by_release[release_id],
        "model_name": casting_name,
        "existing_casting_id": casting_id,
        "source_record_ids": sorted(sources_by_release[release_id]),
        "evidence_review_status_counts": evidence_status_by_release[release_id],
    } for release_id, casting_name, release_year, casting_id in releases]

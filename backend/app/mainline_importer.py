"""Conservative importer from a parsed Fandom Mainline snapshot into a test catalog.

The importer stores candidate records and source evidence. It never confirms identity,
overwrites catalog fields, or touches the legacy collection.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .identifier_normalization import normalize_identifier
from .models import (
    CatalogIdentifier,
    CatalogNode,
    Casting,
    Evidence,
    EvidenceCasting,
    EvidenceRelease,
    EvidenceSeries,
    IdentifierType,
    ProductLine,
    Release,
    ReleaseIdentifier,
    ReleaseSeries,
    Series,
    Source,
    SourceRecord,
)

SOURCE_NAME = "Hot Wheels Wiki (Fandom)"
SOURCE_URL = "https://hotwheels.fandom.com/wiki/"
SKU_TYPE_CODE = "sku"
CATALOG_NUMBER_TYPE_CODE = "catalog_number"


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _casting_name(model_name: str) -> str:
    """Remove only explicit color-number annotations; preserve other source wording."""
    return re.sub(r"\s+\(\s*\d+(?:st|nd|rd|th)\s+Color\s*\)\s*$", "", model_name, flags=re.I).strip()


def _first_or_create(session: Session, model, *, defaults: dict | None = None, **filters):
    item = session.scalar(select(model).filter_by(**filters).limit(1))
    if item is not None:
        return item, False
    item = model(**filters, **(defaults or {}))
    session.add(item)
    session.flush()
    return item, True


def _ensure_source(session: Session) -> tuple[Source, bool]:
    return _first_or_create(
        session,
        Source,
        name=SOURCE_NAME,
        source_type="wiki",
        defaults={
            "base_url": SOURCE_URL,
            "publisher": "Fandom",
            "is_official": False,
            "access_method": "mediawiki_api",
            "access_status": "available",
            "notes": "Community-maintained reference; source claims remain pending review.",
        },
    )


def _ensure_sku_type(session: Session) -> tuple[IdentifierType, bool]:
    return _first_or_create(
        session,
        IdentifierType,
        code=SKU_TYPE_CODE,
        defaults={
            "label": "Toy SKU",
            "description": "Source-listed toy number/SKU; candidate match key, not proof of release identity.",
            "normalization_rule": "unicode_case_whitespace",
            "is_globally_unique": False,
        },
    )


def _ensure_catalog_number_type(session: Session) -> tuple[IdentifierType, bool]:
    return _first_or_create(
        session,
        IdentifierType,
        code=CATALOG_NUMBER_TYPE_CODE,
        defaults={
            "label": "Collector number",
            "description": "Source-listed annual collector number (Col. #); may repeat across years and is not a global release key.",
            "normalization_rule": "unicode_case_whitespace",
            "is_globally_unique": False,
        },
    )


def _ensure_tree_base(session: Session) -> tuple[CatalogNode, ProductLine, CatalogNode, bool]:
    root = session.scalar(select(CatalogNode).where(CatalogNode.node_type == "root").limit(1))
    root_created = root is None
    if root is None:
        root = CatalogNode(node_type="root", label_override="Catalog", sort_order=0)
        session.add(root)
        session.flush()

    line, line_created = _first_or_create(
        session,
        ProductLine,
        name="Mainline",
        line_type="mainline",
        defaults={
            "description": "Candidate product line imported from Hot Wheels Wiki yearly Mainline tables.",
            "status": "candidate",
        },
    )
    line_node = session.scalar(
        select(CatalogNode).where(
            CatalogNode.node_type == "product_line",
            CatalogNode.product_line_id == line.id,
        ).limit(1)
    )
    if line_node is None:
        line_node = CatalogNode(
            parent_id=root.id,
            node_type="product_line",
            product_line_id=line.id,
            sort_order=0,
        )
        session.add(line_node)
        session.flush()
    return root, line, line_node, root_created or line_created


def _ensure_year_node(session: Session, parent_id: str, year: int) -> tuple[CatalogNode, bool]:
    node = session.scalar(
        select(CatalogNode).where(
            CatalogNode.parent_id == parent_id,
            CatalogNode.node_type == "year",
            CatalogNode.catalog_year == year,
        ).limit(1)
    )
    if node is not None:
        return node, False
    node = CatalogNode(parent_id=parent_id, node_type="year", catalog_year=year, sort_order=year)
    session.add(node)
    session.flush()
    return node, True


def _ensure_series_node(session: Session, year_node_id: str, series: Series, sort_order: int) -> tuple[CatalogNode, bool]:
    node = session.scalar(
        select(CatalogNode).where(
            CatalogNode.parent_id == year_node_id,
            CatalogNode.node_type == "series",
            CatalogNode.series_id == series.id,
        ).limit(1)
    )
    if node is not None:
        return node, False
    node = CatalogNode(
        parent_id=year_node_id,
        node_type="series",
        series_id=series.id,
        sort_order=sort_order,
    )
    session.add(node)
    session.flush()
    return node, True


def _link_evidence(
    session: Session,
    *,
    source_record: SourceRecord,
    attribute: str,
    value: Any,
    release: Release | None = None,
    casting: Casting | None = None,
    series: Series | None = None,
) -> Evidence | None:
    if value is None or value == "" or value == [] or value == {}:
        return None
    observed = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    evidence = Evidence(
        source_record_id=source_record.id,
        attribute_name=attribute,
        observed_value=observed,
        evidence_type="text",
        assessment="supports",
        review_status="pending",
        notes="Imported source observation. Pending review; does not confirm identity or classification.",
    )
    session.add(evidence)
    session.flush()
    if release is not None:
        session.add(EvidenceRelease(evidence_id=evidence.id, release_id=release.id, role="about"))
    if casting is not None:
        session.add(EvidenceCasting(evidence_id=evidence.id, casting_id=casting.id, role="about"))
    if series is not None:
        session.add(EvidenceSeries(evidence_id=evidence.id, series_id=series.id, role="about"))
    return evidence


def import_mainline_snapshot(session: Session, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Import parsed rows into the caller's transaction; caller chooses commit/rollback.

    Re-running the same snapshot is idempotent. Changed source rows create a new
    source snapshot and additional evidence, but do not overwrite catalog fields.
    """
    year = snapshot.get("year")
    if not isinstance(year, int) or not 1968 <= year <= 2100:
        raise ValueError("snapshot.year must be a valid catalog year")
    records = snapshot.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("snapshot.records must be a non-empty list")

    source, source_created = _ensure_source(session)
    sku_type, sku_type_created = _ensure_sku_type(session)
    catalog_number_type, catalog_number_type_created = _ensure_catalog_number_type(session)
    _root, _line, line_node, base_created = _ensure_tree_base(session)
    year_node, year_node_created = _ensure_year_node(session, line_node.id, year)

    stats: Counter[str] = Counter()
    stats["sources_created"] = int(source_created)
    stats["identifier_types_created"] = int(sku_type_created) + int(catalog_number_type_created)
    stats["tree_base_created"] = int(base_created)
    stats["year_nodes_created"] = int(year_node_created)
    warnings: list[dict[str, Any]] = []

    # SKU duplicates are reported but never used to merge or discard rows.
    sku_counts = Counter(
        str(row.get("toy_number", "")).strip().upper()
        for row in records if row.get("toy_number")
    )
    duplicate_skus = sorted(sku for sku, count in sku_counts.items() if count > 1)

    for position, row in enumerate(records, start=1):
        sku = str(row.get("toy_number") or "").strip().upper()
        model_name = str(row.get("model_name") or "").strip()
        if not sku or not model_name:
            stats["invalid_rows"] += 1
            warnings.append({"position": position, "reason": "missing SKU or model name"})
            continue

        source_row = row.get("source_row", position)
        external_id = f"{year}:{source_row}:{sku}"
        row_hash = _json_hash({"year": year, "record": row})
        existing_snapshot = session.scalar(
            select(SourceRecord)
            .where(
                SourceRecord.source_id == source.id,
                SourceRecord.external_id == external_id,
                SourceRecord.content_hash == row_hash,
            )
            .limit(1)
        )
        if existing_snapshot is not None:
            stats["rows_unchanged_skipped"] += 1
            continue

        # Reuse only the release already associated with this exact source-row key.
        prior_release = session.scalar(
            select(Release)
            .join(EvidenceRelease, EvidenceRelease.release_id == Release.id)
            .join(Evidence, Evidence.id == EvidenceRelease.evidence_id)
            .join(SourceRecord, SourceRecord.id == Evidence.source_record_id)
            .where(
                SourceRecord.source_id == source.id,
                SourceRecord.external_id == external_id,
            )
            .limit(1)
        )

        source_record = SourceRecord(
            source_id=source.id,
            external_id=external_id,
            record_url=f"https://hotwheels.fandom.com/wiki/List_of_{year}_Hot_Wheels",
            record_type="mainline_release_row",
            raw_data={"year": year, **row},
            content_hash=row_hash,
            status="active",
        )
        session.add(source_record)
        session.flush()
        stats["source_records_created"] += 1

        casting_name = _casting_name(model_name)
        casting = session.scalar(
            select(Casting).where(Casting.name == casting_name).limit(1)
        )
        if casting is None:
            casting = Casting(
                name=casting_name,
                first_known_year=None,
                status="candidate",
                description="Candidate casting grouping generated from source model names; not manually confirmed.",
            )
            session.add(casting)
            session.flush()
            stats["castings_created"] += 1
        else:
            stats["castings_reused"] += 1

        if prior_release is None:
            release = Release(
                casting_id=casting.id,
                catalog_year=year,
                name=model_name,
                status="candidate",
                description="Candidate yearly release imported from Fandom; source annotations preserved in evidence.",
            )
            session.add(release)
            session.flush()
            stats["releases_created"] += 1
        else:
            release = prior_release
            stats["releases_reused_for_new_snapshot"] += 1

        # SKU is a lookup identifier, not a uniqueness guarantee for the release.
        normalized_sku = normalize_identifier(SKU_TYPE_CODE, sku)
        identifier = session.scalar(
            select(CatalogIdentifier).where(
                CatalogIdentifier.identifier_type_id == sku_type.id,
                CatalogIdentifier.normalized_value == normalized_sku,
            ).limit(1)
        )
        if identifier is None:
            identifier = CatalogIdentifier(
                identifier_type_id=sku_type.id,
                value=sku,
                normalized_value=normalized_sku,
                notes="Observed source SKU; not proof of unique release identity.",
            )
            session.add(identifier)
            session.flush()
            stats["identifiers_created"] += 1
        link = session.get(ReleaseIdentifier, (release.id, identifier.id))
        if link is None:
            session.add(ReleaseIdentifier(
                release_id=release.id,
                identifier_id=identifier.id,
                role="primary",
                source_note=f"Observed in {SOURCE_NAME} row {source_row}; candidate match key only.",
            ))
            stats["release_identifier_links_created"] += 1

        # Col. # is a structured release identifier, not a Casting identity key.
        collector_number = str(row.get("collector_number") or "").strip()
        if collector_number:
            normalized_collector_number = normalize_identifier(
                CATALOG_NUMBER_TYPE_CODE, collector_number
            )
            collector_identifier = session.scalar(
                select(CatalogIdentifier).where(
                    CatalogIdentifier.identifier_type_id == catalog_number_type.id,
                    CatalogIdentifier.normalized_value == normalized_collector_number,
                ).limit(1)
            )
            if collector_identifier is None:
                collector_identifier = CatalogIdentifier(
                    identifier_type_id=catalog_number_type.id,
                    value=collector_number,
                    normalized_value=normalized_collector_number,
                    notes="Observed source Col. #; annual collector number, not a globally unique release key.",
                )
                session.add(collector_identifier)
                session.flush()
                stats["catalog_number_identifiers_created"] += 1
            collector_link = session.get(
                ReleaseIdentifier, (release.id, collector_identifier.id)
            )
            if collector_link is None:
                session.add(ReleaseIdentifier(
                    release_id=release.id,
                    identifier_id=collector_identifier.id,
                    role="secondary",
                    source_note=(
                        f"Observed as Col. # in {SOURCE_NAME} row {source_row}; "
                        "candidate identifier only."
                    ),
                ))
                stats["release_catalog_number_links_created"] += 1

        series = None
        series_node = None
        series_name = row.get("series_name")
        if series_name:
            series = session.scalar(select(Series).where(Series.name == series_name).limit(1))
            if series is None:
                series = Series(
                    name=series_name,
                    series_type="source_label",
                    status="candidate",
                    description="Source-listed series label; normalized classification is not yet confirmed.",
                )
                session.add(series)
                session.flush()
                stats["series_created"] += 1
            else:
                stats["series_reused"] += 1
            release_series = session.get(ReleaseSeries, (release.id, series.id))
            if release_series is None:
                session.add(ReleaseSeries(
                    release_id=release.id,
                    series_id=series.id,
                    relation_note="Membership observed in Fandom yearly Mainline table; pending review.",
                ))
                stats["release_series_links_created"] += 1
            series_node, node_created = _ensure_series_node(
                session, year_node.id, series, int(row.get("source_row") or position)
            )
            stats["series_nodes_created"] += int(node_created)

        release_node_parent = series_node.id if series_node is not None else year_node.id
        release_node = session.scalar(
            select(CatalogNode).where(
                CatalogNode.node_type == "release",
                CatalogNode.release_id == release.id,
            ).limit(1)
        )
        if release_node is None:
            session.add(CatalogNode(
                parent_id=release_node_parent,
                node_type="release",
                release_id=release.id,
                sort_order=int(row.get("source_row") or position),
            ))
            stats["release_nodes_created"] += 1

        # Preserve each source field as separate, pending evidence.
        _link_evidence(session, source_record=source_record, attribute="toy_number", value=sku, release=release)
        _link_evidence(session, source_record=source_record, attribute="model_name", value=model_name, release=release, casting=casting)
        _link_evidence(session, source_record=source_record, attribute="collector_number", value=row.get("collector_number"), release=release)
        _link_evidence(session, source_record=source_record, attribute="series_name", value=series_name, release=release, series=series)
        _link_evidence(session, source_record=source_record, attribute="series_number_raw", value=row.get("series_number_raw"), release=release, series=series)
        annotations = row.get("source_annotations")
        _link_evidence(session, source_record=source_record, attribute="source_annotations", value=annotations, release=release)

    stats["duplicate_sku_values"] = len(duplicate_skus)
    stats["input_rows"] = len(records)
    stats["warnings_count"] = len(warnings)
    return {
        "year": year,
        "source": SOURCE_NAME,
        "dry_run_supported": True,
        "stats": dict(stats),
        "duplicate_skus": duplicate_skus,
        "warnings": warnings,
        "policy": {
            "record_status": "candidate",
            "evidence_review_status": "pending",
            "sku": "lookup key only; never used alone to merge releases",
            "source_annotations": "preserved as raw evidence",
            "catalog_field_overwrite": "none",
            "transaction": "caller must explicitly commit or roll back",
        },
    }

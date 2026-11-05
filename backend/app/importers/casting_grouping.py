"""Pure, read-only Casting grouping proposals from explicit source claims.

This module never reads or writes the database. Collector numbers are scoped by
an explicitly supplied product line and catalog year; model names and SKUs are
descriptive/release-level data, never Casting identity keys.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _key_part(value: Any) -> str | None:
    text = _clean_text(value)
    return text.casefold() if text is not None else None


def _claim_value(claim: Any) -> str | None:
    if isinstance(claim, dict):
        return _clean_text(claim.get("value"))
    return _clean_text(claim)


def _record_sort_key(record: dict[str, Any]) -> tuple[str, str]:
    return (
        str(record.get("release_id") or ""),
        str(record.get("record_id") or ""),
    )


def build_casting_grouping_preview(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build explainable provisional Casting groups without persistence.

    Each record must have a stable record_id and may provide product_line,
    catalog_year, collector_number_claims, sku, model_name, release_id,
    existing_casting_id and source_record_ids. A usable record needs exactly
    one distinct non-empty collector-number value plus product line and year.
    """
    if not isinstance(records, list):
        raise ValueError("records must be a list")

    normalized: list[dict[str, Any]] = []
    seen_record_ids: set[str] = set()
    for index, source in enumerate(records):
        if not isinstance(source, dict):
            raise ValueError(f"record at index {index} must be an object")
        record_id = _clean_text(source.get("record_id"))
        if not record_id:
            raise ValueError(f"record at index {index} requires record_id")
        if record_id in seen_record_ids:
            raise ValueError(f"duplicate record_id: {record_id}")
        seen_record_ids.add(record_id)

        claims = source.get("collector_number_claims") or []
        if not isinstance(claims, list):
            raise ValueError(f"collector_number_claims for {record_id} must be a list")
        claim_values: dict[str, str] = {}
        claim_details: list[dict[str, Any]] = []
        for claim in claims:
            value = _claim_value(claim)
            if value is None:
                continue
            claim_values.setdefault(value.casefold(), value)
            if isinstance(claim, dict):
                claim_details.append({
                    "value": value,
                    "source_record_id": claim.get("source_record_id"),
                    "source_field": claim.get("source_field") or "collector_number",
                })
            else:
                claim_details.append({
                    "value": value,
                    "source_record_id": None,
                    "source_field": "collector_number",
                })

        product_line = _clean_text(source.get("product_line"))
        year = source.get("catalog_year")
        if year is not None:
            try:
                year = int(year)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"catalog_year for {record_id} must be an integer") from exc
            if year < 1968 or year > 2100:
                raise ValueError(f"catalog_year for {record_id} must be between 1968 and 2100")

        normalized.append({
            "record_id": record_id,
            "release_id": _clean_text(source.get("release_id")),
            "product_line": product_line,
            "product_line_key": _key_part(product_line),
            "catalog_year": year,
            "collector_number": next(iter(claim_values.values())) if len(claim_values) == 1 else None,
            "collector_number_key": next(iter(claim_values)) if len(claim_values) == 1 else None,
            "claim_values": list(claim_values.values()),
            "collector_number_claims": claim_details,
            "sku": sorted({
                text for value in (source.get("sku") or [])
                if (text := _clean_text(value)) is not None
            }) if isinstance(source.get("sku") or [], list) else [],
            "model_name": _clean_text(source.get("model_name")),
            "existing_casting_id": _clean_text(source.get("existing_casting_id")),
            "source_record_ids": sorted({
                text for value in (source.get("source_record_ids") or [])
                if (text := _clean_text(value)) is not None
            }) if isinstance(source.get("source_record_ids") or [], list) else [],
        })

    # A Release can have several source snapshots. Conflicting Col.# claims
    # across those snapshots must be reviewed as one Release-level conflict.
    release_claim_values: dict[str, set[str]] = defaultdict(set)
    release_claim_details: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in normalized:
        release_id = record["release_id"]
        if not release_id:
            continue
        for claim in record["collector_number_claims"]:
            value = _clean_text(claim.get("value"))
            if value is not None:
                release_claim_values[release_id].add(value.casefold())
                release_claim_details[release_id].append(claim)

    keyed: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    manual_review: list[dict[str, Any]] = []
    for record in normalized:
        reasons: list[str] = []
        release_id = record["release_id"]
        if release_id and len(release_claim_values[release_id]) > 1:
            reasons.append("conflicting_collector_number_claims_for_release")
        if record["product_line_key"] is None:
            reasons.append("missing_product_line")
        if record["catalog_year"] is None:
            reasons.append("missing_catalog_year")
        if not record["claim_values"]:
            reasons.append("missing_collector_number")
        elif len(record["claim_values"]) > 1:
            reasons.append("conflicting_collector_number_claims")

        if reasons:
            manual_review.append({
                "record_id": record["record_id"],
                "release_id": record["release_id"],
                "sku": record["sku"],
                "model_name": record["model_name"],
                "collector_number_claims": (
                    release_claim_details[release_id]
                    if release_id and len(release_claim_values[release_id]) > 1
                    else record["collector_number_claims"]
                ),
                "reason_codes": reasons,
                "requires_manual_review": True,
                "reason": "Insufficient or contradictory identity context; no name-based fallback is permitted.",
            })
            continue

        key = (
            record["product_line_key"],
            record["catalog_year"],
            record["collector_number_key"],
        )
        keyed[key].append(record)

    groups: list[dict[str, Any]] = []
    key_to_group: dict[tuple[str, int, str], dict[str, Any]] = {}
    for index, (key, members) in enumerate(sorted(keyed.items()), start=1):
        members.sort(key=_record_sort_key)
        casting_ids = sorted({
            member["existing_casting_id"]
            for member in members if member["existing_casting_id"] is not None
        })
        conflicts: list[dict[str, Any]] = []
        if len(casting_ids) > 1:
            conflicts.append({
                "code": "group_spans_multiple_existing_castings",
                "existing_casting_ids": casting_ids,
                "message": "The same proposed key currently points to multiple Castings; no merge is proposed.",
            })

        group = {
            "proposal_id": f"casting-proposal-{index:04d}",
            "group_key": {
                "product_line": members[0]["product_line"],
                "catalog_year": key[1],
                "collector_number": members[0]["collector_number"],
            },
            "status": "manual_review" if conflicts else "proposed",
            "requires_manual_review": bool(conflicts),
            "reasons": [
                "same_explicit_product_line",
                "same_catalog_year",
                "same_explicit_collector_number",
                "sku_identifies_release_not_casting",
                "model_name_is_not_a_grouping_key",
            ],
            "conflicts": conflicts,
            "records": [{
                "record_id": member["record_id"],
                "release_id": member["release_id"],
                "sku": member["sku"],
                "model_name": member["model_name"],
                "existing_casting_id": member["existing_casting_id"],
                "collector_number_claims": member["collector_number_claims"],
                "source_record_ids": member["source_record_ids"],
            } for member in members],
        }
        groups.append(group)
        key_to_group[key] = group

    # One current Casting spanning distinct proposed keys is a split conflict.
    existing_to_keys: dict[str, set[tuple[str, int, str]]] = defaultdict(set)
    for key, members in keyed.items():
        for member in members:
            if member["existing_casting_id"]:
                existing_to_keys[member["existing_casting_id"]].add(key)

    cross_key_conflicts = []
    for casting_id, keys in sorted(existing_to_keys.items()):
        if len(keys) < 2:
            continue
        affected = [key_to_group[key] for key in sorted(keys)]
        conflict = {
            "code": "existing_casting_spans_multiple_proposed_groups",
            "existing_casting_id": casting_id,
            "proposal_ids": [group["proposal_id"] for group in affected],
            "message": "One existing Casting spans different product-line/year/collector-number keys; proposals remain separate and require review.",
        }
        cross_key_conflicts.append(conflict)
        for group in affected:
            group["status"] = "manual_review"
            group["requires_manual_review"] = True
            group["conflicts"].append(conflict)

    duplicate_key_conflicts = [
        conflict
        for group in groups
        for conflict in group["conflicts"]
        if conflict["code"] == "group_spans_multiple_existing_castings"
    ]
    return {
        "contract": "hw_catalog.casting_grouping_preview",
        "contract_version": 1,
        "mode": "preview_only",
        "writes_to_catalog": False,
        "grouping_key": ["product_line", "catalog_year", "collector_number"],
        "groups": groups,
        "manual_review": sorted(manual_review, key=lambda item: item["record_id"]),
        "conflicts": cross_key_conflicts + duplicate_key_conflicts,
        "summary": {
            "records_received": len(normalized),
            "proposed_groups": len(groups),
            "records_requiring_manual_review": len(manual_review),
            "groups_requiring_manual_review": sum(
                group["requires_manual_review"] for group in groups
            ),
            "conflicts": len(cross_key_conflicts) + len(duplicate_key_conflicts),
        },
    }

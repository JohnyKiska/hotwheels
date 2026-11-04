"""Pure, non-writing attribute diff for one selected Release candidate."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


# Only attributes with a direct, currently implemented canonical field are
# compared against catalog values. Everything else remains source evidence.
_CANONICAL_FIELDS = {
    "model_name": "name",
    "catalog_year": "catalog_year",
    "assortment_number": "assortment_number",
    "series_name": "series_names",
}


def _value_key(value: Any) -> str | None:
    if value is None or value == "" or value == [] or value == {}:
        return None
    if isinstance(value, list):
        parts = [_value_key(item) for item in value]
        return "|".join(sorted(part for part in parts if part is not None))
    normalized = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def build_release_claim_diff(
    observation: dict[str, Any],
    release_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Compare source claims with an explicitly selected Release snapshot.

    Expected release_snapshot keys: id, name, catalog_year, assortment_number,
    casting_name, and optional series_names. The function performs no I/O and
    cannot persist or apply any proposed action.
    """
    if not isinstance(observation, dict) or not isinstance(release_snapshot, dict):
        raise ValueError("Observation and Release snapshot must be objects.")
    if observation.get("mode") not in (None, "preview_only"):
        raise ValueError("Only preview observations can be diffed.")
    if observation.get("writes_to_catalog") not in (None, False):
        raise ValueError("Preview diff accepts read-only observations only.")
    claims = observation.get("claims") or []
    if not isinstance(claims, list):
        raise ValueError("Observation claims must be a list.")
    release_id = release_snapshot.get("id")
    if not release_id:
        raise ValueError("A selected Release ID is required.")

    rows: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("Each claim must be an object.")
        attribute = claim.get("attribute")
        incoming = claim.get("value")
        raw_value = claim.get("raw_value")
        base = {
            "attribute": attribute,
            "incoming_value": incoming,
            "raw_value": raw_value,
            "source_field": claim.get("source_field"),
            "claim_status": claim.get("claim_status", "observed"),
        }
        if _value_key(incoming) is None:
            rows.append({
                **base,
                "status": "insufficient_evidence",
                "existing_value": None,
                "suggested_action": "manual_review",
                "reason": "The source claim has no usable value.",
            })
            continue

        canonical_field = _CANONICAL_FIELDS.get(attribute)
        if canonical_field is None:
            rows.append({
                **base,
                "status": "evidence_only",
                "existing_value": None,
                "suggested_action": "attach_evidence_after_confirmation",
                "reason": "No direct canonical field is currently defined for this attribute.",
            })
            continue

        if canonical_field == "name":
            existing = release_snapshot.get("name") or release_snapshot.get("casting_name")
        elif canonical_field == "series_names":
            existing = release_snapshot.get("series_names") or []
        else:
            existing = release_snapshot.get(canonical_field)

        if _value_key(existing) is None:
            status = "new_evidence"
            action = "attach_evidence_after_confirmation"
            reason = "The selected Release has no canonical value for this attribute."
        elif _value_key(existing) == _value_key(incoming):
            status = "same"
            action = "no_change"
            reason = "The incoming value matches the selected Release snapshot."
        else:
            status = "conflicting_value"
            action = "review_conflict"
            reason = "The incoming value differs from the selected Release snapshot; neither value is changed."

        rows.append({
            **base,
            "status": status,
            "existing_value": existing,
            "canonical_field": canonical_field,
            "suggested_action": action,
            "reason": reason,
        })

    counts = {key: 0 for key in (
        "same", "new_evidence", "conflicting_value",
        "insufficient_evidence", "evidence_only",
    )}
    for row in rows:
        counts[row["status"]] += 1

    return {
        "contract": "hw_catalog.release_claim_diff",
        "contract_version": 1,
        "mode": "preview_only",
        "writes_to_catalog": False,
        "selected_entity": {"entity_type": "release", "entity_id": release_id},
        "claims": rows,
        "summary": {"claims_compared": len(rows), **counts},
    }

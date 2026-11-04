"""Pure in-memory adapters from source-specific previews to observations.

No database access, network fetching, matching, or catalog writes occur here.
"""
from __future__ import annotations

from typing import Any


_FIELD_MAP = (
    ("name", "model_name"),
    ("catalog_year", "catalog_year"),
    ("release_year", "release_year"),
    ("toy_number", "toy_number"),
    ("assortment_number", "assortment_number"),
    ("collector_number", "collector_number"),
    ("mainline_number", "mainline_number"),
    ("mainline_total", "mainline_total"),
    ("mainline_numbering_statement", "mainline_numbering_statement"),
    ("series_name", "series_name"),
    ("series_index", "series_index"),
    ("series_total", "series_total"),
    ("rarity", "rarity"),
    ("special_label", "special_label"),
    ("category", "product_category"),
    ("scale", "scale"),
    ("base_material", "base_material"),
    ("wheels", "wheels"),
    ("colors", "colors"),
    ("tags", "tags"),
    ("notes", "source_notes"),
)


def _source_profile(preview: dict[str, Any]) -> tuple[str, str, str]:
    importer = preview.get("importer")
    source_format = preview.get("source_format")

    if importer == "mainline" and source_format == "fandom_yearly_html":
        return "fandom", "mainline_yearly_row", source_format
    if importer == "mainline" and source_format is None:
        return "mainline_checklist", "mainline_checklist_row", "tsv"
    if importer == "all_hot_wheels" and source_format == "all_hot_wheels_car_html":
        return "all_hot_wheels", "car_detail", source_format

    raise ValueError(
        f"Unsupported importer/source format combination: {importer!r}/{source_format!r}"
    )


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def preview_to_observations(preview: dict[str, Any]) -> dict[str, Any]:
    """Convert a read-only parser result to a versioned observation envelope.

    Source-specific raw values and parser issues are retained. The function
    deliberately emits identifier *hints*, not canonical identifier links.
    """
    if not isinstance(preview, dict):
        raise ValueError("Preview result must be an object.")
    if preview.get("mode") != "preview_only" or preview.get("writes_to_catalog") is not False:
        raise ValueError("Only explicitly read-only preview results can be adapted.")

    source_code, record_type, source_format = _source_profile(preview)
    records = preview.get("records")
    if not isinstance(records, list):
        raise ValueError("Preview result must contain a records list.")

    observations: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Each preview record must be an object.")

        source_fields = record.get("source_fields") or {}
        source_values = record.get("source_values") or {}
        if not isinstance(source_fields, dict) or not isinstance(source_values, dict):
            raise ValueError("source_fields and source_values must be objects when supplied.")

        claims: list[dict[str, Any]] = []
        for source_key, attribute in _FIELD_MAP:
            value = record.get(source_key)
            if not _present(value):
                continue
            source_field = source_fields.get(source_key) or source_key
            raw_value = source_values.get(source_field, value)
            claims.append({
                "attribute": attribute,
                "value": value,
                "raw_value": raw_value,
                "source_field": source_field,
                "claim_status": "observed",
            })

        toy_number = record.get("toy_number")
        identifier_hints = []
        if _present(toy_number):
            identifier_hints.append({
                "type_code": "sku" if source_code == "all_hot_wheels" else "toy_number",
                "raw_value": toy_number,
                "source_field": source_fields.get("toy_number") or (
                    "SKU" if source_code == "all_hot_wheels" else "Toy #"
                ),
            })

        catalog_year = record.get("catalog_year")
        release_year = record.get("release_year")
        subject_hints = {
            "catalog_year": catalog_year,
            "release_year": release_year,
            "name": record.get("name"),
            "toy_number": toy_number,
            "assortment_number": record.get("assortment_number"),
            "collector_number": record.get("collector_number"),
            "series_name": record.get("series_name"),
        }

        raw = {
            "source_fields": source_fields,
            "source_values": source_values,
            "raw_text": record.get("raw_text"),
            "source_row": record.get("source_row"),
            "raw_title": record.get("raw_title"),
            "series_summary_raw": record.get("series_summary_raw"),
        }
        observations.append({
            "source": {
                "code": source_code,
                "record_type": record_type,
                "format": source_format,
                "record_url": record.get("source_url") or preview.get("source_url"),
                # A toy number/SKU is not assumed to be a globally unique source-record ID.
                "external_id": None,
            },
            "subject_hints": subject_hints,
            "claims": claims,
            "identifier_hints": identifier_hints,
            "raw": raw,
            "review_status": "candidate",
        })

    issues = preview.get("issues") or []
    summary = preview.get("summary") or {}
    return {
        "contract": "hw_catalog.import_observation",
        "contract_version": 1,
        "mode": "preview_only",
        "writes_to_catalog": False,
        "source": {
            "code": source_code,
            "record_type": record_type,
            "format": source_format,
            "record_url": preview.get("source_url"),
        },
        "observations": observations,
        "issues": issues,
        "summary": {
            "observations_found": len(observations),
            "parser_records_found": summary.get("records_found", len(records)),
            "errors": summary.get("errors", 0),
            "warnings": summary.get("warnings", 0),
        },
    }

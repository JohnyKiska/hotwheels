"""Conservative, read-only matching for normalized import observations.

The matcher proposes candidates and explains its signals. It never writes,
registers identifiers, creates conflicts, confirms records, or merges entities.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..identifier_normalization import normalize_identifier
from ..models import (
    Casting,
    CastingIdentifier,
    CatalogIdentifier,
    IdentifierType,
    Release,
    ReleaseIdentifier,
    SourceRecord,
)


def _name_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _source_replay(
    session: Session, source_snapshot: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not isinstance(source_snapshot, dict):
        return None
    source_id = source_snapshot.get("source_id")
    content_hash = source_snapshot.get("content_hash")
    if not source_id or not content_hash:
        return None
    record = session.scalar(
        select(SourceRecord).where(
            SourceRecord.source_id == source_id,
            SourceRecord.content_hash == content_hash,
        ).order_by(SourceRecord.id)
    )
    if record is None:
        return None
    return {
        "status": "exact_source_replay",
        "matched_entities": [],
        "source_record_id": record.id,
        "signals": [{
            "kind": "source_snapshot",
            "source_record_id": record.id,
            "reason": "Source ID and immutable content hash match an existing snapshot.",
        }],
        "contradictions": [],
        "requires_manual_review": False,
        "mode": "preview_only",
        "writes_to_catalog": False,
    }


def match_import_observation(
    session: Session,
    observation: dict[str, Any],
    *,
    source_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an explainable Release match result using SELECTs only.

    source_snapshot is optional because parser observations do not yet carry
    persisted SourceRecord IDs or content hashes. Without both values, replay
    detection is deliberately not inferred from a URL or SKU.
    """
    if not isinstance(observation, dict):
        raise ValueError("Observation must be an object.")
    if observation.get("mode") not in (None, "preview_only"):
        raise ValueError("Only preview observations can be matched.")
    if observation.get("writes_to_catalog") not in (None, False):
        raise ValueError("Matcher accepts read-only observations only.")
    claims = observation.get("claims") or []
    hints = observation.get("identifier_hints") or []
    subject = observation.get("subject_hints") or {}
    if not isinstance(claims, list) or not isinstance(hints, list) or not isinstance(subject, dict):
        raise ValueError("Observation claims, identifier_hints, and subject_hints must be valid objects/lists.")

    replay = _source_replay(session, source_snapshot)
    if replay is not None:
        return replay

    candidates: dict[str, dict[str, Any]] = {}
    collision_hints: list[dict[str, Any]] = []
    ignored_hints: list[dict[str, Any]] = []

    def add_release(release_id: str, signal: dict[str, Any]) -> None:
        candidate = candidates.setdefault(release_id, {
            "entity_type": "release",
            "entity_id": release_id,
            "signals": [],
        })
        if signal not in candidate["signals"]:
            candidate["signals"].append(signal)

    for hint in hints:
        if not isinstance(hint, dict):
            continue
        type_code = hint.get("type_code")
        raw_value = hint.get("raw_value")
        if not isinstance(type_code, str) or not isinstance(raw_value, str) or not raw_value.strip():
            continue
        identifier_type = session.scalar(
            select(IdentifierType).where(IdentifierType.code == type_code.strip().casefold())
        )
        if identifier_type is None:
            ignored_hints.append({
                "type_code": type_code,
                "raw_value": raw_value,
                "reason": "Identifier namespace is not configured in the catalog.",
            })
            continue
        try:
            normalized = normalize_identifier(identifier_type.code, raw_value)
        except ValueError as exc:
            ignored_hints.append({
                "type_code": type_code,
                "raw_value": raw_value,
                "reason": str(exc),
            })
            continue
        identifier = session.scalar(
            select(CatalogIdentifier).where(
                CatalogIdentifier.identifier_type_id == identifier_type.id,
                CatalogIdentifier.normalized_value == normalized,
            )
        )
        if identifier is None:
            continue

        release_ids = set(session.scalars(
            select(ReleaseIdentifier.release_id).where(
                ReleaseIdentifier.identifier_id == identifier.id
            )
        ).all())
        if len(release_ids) > 1:
            collision_hints.append({
                "type_code": identifier_type.code,
                "raw_value": raw_value,
                "identifier_id": identifier.id,
                "release_ids": sorted(release_ids),
                "reason": "The same normalized identifier is assigned to multiple Releases.",
            })
        for release_id in release_ids:
            add_release(release_id, {
                "kind": "release_identifier",
                "type_code": identifier_type.code,
                "raw_value": raw_value,
                "identifier_id": identifier.id,
                "reason": "Exact normalized identifier is assigned to this Release.",
            })

        casting_ids = set(session.scalars(
            select(CastingIdentifier.casting_id).where(
                CastingIdentifier.identifier_id == identifier.id
            )
        ).all())
        if casting_ids:
            for release_id in session.scalars(
                select(Release.id).where(Release.casting_id.in_(casting_ids))
            ).all():
                add_release(release_id, {
                    "kind": "casting_identifier",
                    "type_code": identifier_type.code,
                    "raw_value": raw_value,
                    "identifier_id": identifier.id,
                    "reason": "Identifier is assigned to the Release's Casting, not to this Release.",
                })

    observed_name = _name_key(subject.get("name"))
    catalog_year = subject.get("catalog_year")
    if observed_name:
        rows = session.execute(
            select(Release, Casting).join(Casting, Release.casting_id == Casting.id)
        ).all()
        for release, casting in rows:
            catalog_name = _name_key(release.name) or _name_key(casting.name)
            if catalog_name != observed_name:
                continue
            if catalog_year is not None and release.catalog_year == catalog_year:
                signal = {
                    "kind": "exact_name_and_catalog_year",
                    "observed_name": subject.get("name"),
                    "catalog_year": catalog_year,
                    "reason": "Normalized name and catalog year both match exactly.",
                }
            else:
                signal = {
                    "kind": "exact_name",
                    "observed": subject.get("name"),
                    "reason": "Normalized name matches the Release name or its Casting name exactly.",
                }
            add_release(release.id, signal)

    enriched: list[dict[str, Any]] = []
    for release_id, candidate in sorted(candidates.items()):
        row = session.execute(
            select(Release, Casting)
            .join(Casting, Release.casting_id == Casting.id)
            .where(Release.id == release_id)
        ).first()
        if row is None:
            continue
        release, casting = row
        signals = candidate["signals"]
        has_release_identifier = any(s["kind"] == "release_identifier" for s in signals)
        has_exact_name_year = any(s["kind"] == "exact_name_and_catalog_year" for s in signals)
        strong = has_release_identifier and (
            catalog_year is None or release.catalog_year == catalog_year
        ) or has_exact_name_year
        enriched.append({
            **candidate,
            "name": release.name or casting.name,
            "catalog_year": release.catalog_year,
            "casting_id": casting.id,
            "casting_name": casting.name,
            "signals": signals,
            "strength": "strong" if strong else "weak",
        })

    if collision_hints:
        status = "identifier_collision"
    elif not enriched:
        status = "no_match"
    elif len(enriched) > 1:
        status = "ambiguous"
    elif enriched[0]["strength"] == "strong":
        status = "strong_candidate"
    else:
        status = "ambiguous"

    return {
        "status": status,
        "matched_entities": enriched,
        "signals": [signal for item in enriched for signal in item["signals"]],
        "contradictions": collision_hints,
        "ignored_identifier_hints": ignored_hints,
        "requires_manual_review": status != "no_match",
        "mode": "preview_only",
        "writes_to_catalog": False,
    }

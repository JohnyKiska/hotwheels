"""Persist approved import observations as immutable source snapshots and evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ChangeLog, Evidence, Source, SourceRecord

SOURCE_REGISTRY = {
    "mainline_checklist": {"name": "Hot Wheels Mainline Checklist", "source_type": "catalog"},
    "fandom": {"name": "Hot Wheels Wiki (Fandom)", "source_type": "website"},
    "all_hot_wheels": {"name": "All Hot Wheels", "source_type": "website"},
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _claim_value(value: Any) -> str:
    return value if isinstance(value, str) else _canonical_json(value)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_for_code(session: Session, code: str) -> Source:
    profile = SOURCE_REGISTRY.get(code)
    if profile is None:
        raise ValueError(f"Unsupported import source code: {code!r}")
    source = session.scalar(select(Source).where(Source.code == code))
    if source is not None:
        return source
    legacy = session.scalars(select(Source).where(Source.name == profile["name"], Source.code.is_(None))).all()
    if len(legacy) > 1:
        raise ValueError(f"Multiple legacy Source rows match {code!r}; resolve them manually.")
    if legacy:
        source = legacy[0]
        source.code = code
        session.flush()
        return source
    source = Source(code=code, name=profile["name"], source_type=profile["source_type"],
                    is_official=False, access_status="unknown")
    session.add(source)
    session.flush()
    return source


def apply_import_observation(session: Session, observation: dict[str, Any], *,
                             actor_id: str, reason: str | None = None) -> dict[str, Any]:
    """Persist one approved observation; never create or mutate catalog entities."""
    if not isinstance(observation, dict):
        raise ValueError("Observation must be an object.")
    source_info, claims = observation.get("source"), observation.get("claims")
    if not isinstance(source_info, dict) or not isinstance(claims, list):
        raise ValueError("Observation requires a source object and claims list.")
    code, record_type = source_info.get("code"), source_info.get("record_type")
    if not isinstance(code, str) or not isinstance(record_type, str) or not record_type.strip():
        raise ValueError("Observation source code and record_type are required.")
    if len(record_type) > 40:
        raise ValueError("Observation record_type is too long.")

    raw = observation.get("raw") or {}
    if not isinstance(raw, dict):
        raise ValueError("Observation raw data must be an object.")
    snapshot = {
        "source": source_info,
        "subject_hints": observation.get("subject_hints") or {},
        "claims": claims,
        "identifier_hints": observation.get("identifier_hints") or [],
        "raw": raw,
    }
    content_json = _canonical_json(snapshot)
    content_hash = _sha256(content_json)
    external_id, record_url = source_info.get("external_id"), source_info.get("record_url")
    row_identity = raw.get("source_row")
    if external_id:
        identity = f"external:{external_id}"
    elif row_identity is not None:
        identity = f"row:{row_identity}"
    elif record_url:
        identity = f"url:{record_url}"
    else:
        identity = f"content:{content_hash}"
    import_key = _sha256(_canonical_json([record_type, identity, content_hash]))

    source = _source_for_code(session, code)
    now = datetime.now(timezone.utc)
    record = session.scalar(select(SourceRecord).where(
        SourceRecord.source_id == source.id, SourceRecord.import_key == import_key))
    record_created = record is None
    if record is None:
        record = SourceRecord(
            source_id=source.id, import_key=import_key,
            external_id=str(external_id)[:240] if external_id is not None else None,
            record_url=str(record_url) if record_url is not None else None,
            record_type=record_type.strip(), raw_data=snapshot, content_hash=content_hash,
            retrieved_at=now, last_seen_at=now, status="active")
        session.add(record)
        session.flush()
    else:
        record.last_seen_at = now

    evidence_created = 0
    seen_claims: set[tuple[str, str]] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("Every claim must be an object.")
        attribute, value = claim.get("attribute"), claim.get("value")
        if not isinstance(attribute, str) or not attribute.strip() or len(attribute) > 120:
            raise ValueError("Every claim requires a valid attribute.")
        if value is None:
            continue
        observed_value = _claim_value(value)
        claim_key = (attribute.strip(), observed_value)
        if claim_key in seen_claims:
            continue
        seen_claims.add(claim_key)
        existing = session.scalar(select(Evidence.id).where(
            Evidence.source_record_id == record.id,
            Evidence.attribute_name == attribute.strip(),
            Evidence.observed_value == observed_value))
        if existing is not None:
            continue
        session.add(Evidence(
            source_record_id=record.id, attribute_name=attribute.strip(),
            observed_value=observed_value, evidence_type="text", assessment="supports",
            review_status="pending",
            notes="Imported observation; raw source value and parser field are retained in SourceRecord.raw_data."))
        evidence_created += 1

    session.flush()
    if record_created or evidence_created:
        session.add(ChangeLog(
            entity_type="source_record", entity_id=record.id,
            action="import_observation_applied", old_values=None,
            new_values={"source_code": code, "content_hash": content_hash,
                        "import_key": import_key, "evidence_created": evidence_created},
            reason=(reason or "").strip() or "Apply reviewed import observation",
            actor_type="human", actor_id=actor_id))
        session.flush()

    return {
        "source_id": source.id, "source_record_id": record.id,
        "record_created": record_created, "evidence_created": evidence_created,
        "evidence_total": len(claims), "import_key": import_key,
        "content_hash": content_hash, "writes_to_catalog_entities": False,
    }

"""Read-only administration endpoints for imported source records."""
from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .account_api import _require_permission
from .db import get_db
from .models import SourceRecord, User

router = APIRouter(prefix="/api/v1/admin/imports", tags=["admin-imports"])

RECORD_TYPE = "car_culture_release"
REVIEW_STATUSES = {"pending", "auto_reviewed", "manually_verified", "rejected"}


def _plain(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return value


def _claims(record: SourceRecord) -> dict[str, Any]:
    raw = record.raw_data if isinstance(record.raw_data, dict) else {}
    claims = raw.get("claims", {})

    if isinstance(claims, dict):
        return claims

    if isinstance(claims, list):
        result = {}
        for item in claims:
            if isinstance(item, dict) and item.get("attribute"):
                result[item["attribute"]] = item.get("value")
        return result

    return {}


def _claim(record: SourceRecord, key: str) -> Any:
    value = _claims(record).get(key)
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _evidence_payload(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "attribute_name": item.attribute_name,
        "observed_value": item.observed_value,
        "evidence_type": _plain(item.evidence_type),
        "assessment": _plain(item.assessment),
        "review_status": _plain(item.review_status),
        "notes": item.notes,
    }


def _payload(record: SourceRecord, include_evidence: bool = False) -> dict[str, Any]:
    source = record.source
    evidence = list(record.evidence or [])
    review_counts = Counter(str(_plain(e.review_status)) for e in evidence)

    result = {
        "id": record.id,
        "external_id": record.external_id,
        "import_key": record.import_key,
        "record_type": record.record_type,
        "record_url": record.record_url,
        "status": _plain(record.status),
        "retrieved_at": record.retrieved_at.isoformat() if record.retrieved_at else None,
        "last_seen_at": record.last_seen_at.isoformat() if record.last_seen_at else None,
        "source": {
            "id": source.id,
            "code": source.code,
            "name": source.name,
            "base_url": source.base_url,
        } if source else None,
        "model_name": _claim(record, "model_name"),
        "toy_number": _claim(record, "toy_number"),
        "catalog_year": _claim(record, "catalog_year"),
        "series_name": _claim(record, "series_name"),
        "series_number": _claim(record, "series_number"),
        "product_line": _claim(record, "product_line"),
        "body_color": _claim(record, "body_color"),
        "rarity": _claim(record, "rarity"),
        "casting_linkage": _claim(record, "casting_linkage"),
        "image_blister_url": _claim(record, "image_blister_url"),
        "image_loose_url": _claim(record, "image_loose_url"),
        "image_blister_status": _claim(record, "image_blister_status"),
        "image_loose_status": _claim(record, "image_loose_status"),
        "evidence_count": len(evidence),
        "review_counts": dict(review_counts),
    }
    if include_evidence:
        result["evidence"] = [_evidence_payload(e) for e in evidence]
        result["raw_data"] = record.raw_data
    return result


def _records(db: Session) -> list[SourceRecord]:
    statement = (
        select(SourceRecord)
        .where(SourceRecord.record_type == RECORD_TYPE)
        .options(
            selectinload(SourceRecord.source),
            selectinload(SourceRecord.evidence),
        )
        .order_by(SourceRecord.external_id.asc())
    )
    return list(db.scalars(statement).all())


@router.get("")
def list_imported_records(
    q: str | None = Query(default=None, max_length=240),
    series: str | None = Query(default=None, max_length=240),
    catalog_year: int | None = Query(default=None, ge=1968, le=2100),
    review_status: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if review_status and review_status not in REVIEW_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid review_status.")

    rows = _records(db)
    if q:
        needle = q.casefold()
        rows = [
            row for row in rows
            if needle in " ".join(str(value or "") for value in (
                row.external_id, row.import_key,
                _claim(row, "model_name"), _claim(row, "toy_number"),
                _claim(row, "series_name"),
            )).casefold()
        ]
    if series:
        needle = series.casefold()
        rows = [
            row for row in rows
            if needle in str(_claim(row, "series_name") or "").casefold()
        ]
    if catalog_year is not None:
        rows = [
            row for row in rows
            if str(_claim(row, "catalog_year") or "") == str(catalog_year)
        ]
    if review_status:
        rows = [
            row for row in rows
            if any(str(_plain(e.review_status)) == review_status for e in row.evidence)
        ]

    total = len(rows)
    items = [_payload(row) for row in rows[offset:offset + limit]]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{record_id}")
def get_imported_record(
    record_id: str,
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    record = db.scalar(
        select(SourceRecord)
        .where(
            SourceRecord.id == record_id,
            SourceRecord.record_type == RECORD_TYPE,
        )
        .options(
            selectinload(SourceRecord.source),
            selectinload(SourceRecord.evidence),
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Imported record not found.")
    return _payload(record, include_evidence=True)

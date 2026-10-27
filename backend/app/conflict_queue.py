"""Read-only queue queries for human review of catalog conflicts."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from .models import Conflict, ConflictEvidence, Evidence, SourceRecord, Source


ALLOWED_STATUSES = {"open", "under_review", "resolved", "accepted_difference"}
ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}


def list_conflicts(
    session: Session,
    *,
    status: str | None = None,
    severity: str | None = None,
    conflict_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return a stable, read-only paginated conflict queue.

    The default queue contains unresolved work only. This function never changes
    conflict/evidence/entity statuses and never chooses a winning claim.
    """
    if status is not None and status not in ALLOWED_STATUSES:
        raise ValueError("unsupported conflict status")
    if severity is not None and severity not in ALLOWED_SEVERITIES:
        raise ValueError("unsupported conflict severity")
    if conflict_type is not None and not conflict_type.strip():
        raise ValueError("conflict_type must not be blank")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    predicates = []
    effective_status = status
    if effective_status is None:
        predicates.append(Conflict.status.in_(("open", "under_review")))
    else:
        predicates.append(Conflict.status == effective_status)
    if severity is not None:
        predicates.append(Conflict.severity == severity)
    if conflict_type is not None:
        predicates.append(Conflict.conflict_type == conflict_type.strip())

    count_stmt = select(Conflict.id).where(*predicates)
    total = len(session.scalars(count_stmt).all())
    stmt = (
        select(Conflict)
        .where(*predicates)
        .options(
            selectinload(Conflict.evidence_links)
            .joinedload(ConflictEvidence.evidence)
            .joinedload(Evidence.source_record)
            .joinedload(SourceRecord.source)
        )
        .order_by(Conflict.created_at.asc(), Conflict.id.asc())
        .offset(offset)
        .limit(limit)
    )
    items = []
    for conflict in session.scalars(stmt).unique().all():
        evidence_items = []
        for link in sorted(conflict.evidence_links, key=lambda item: item.evidence_id):
            evidence = link.evidence
            record = evidence.source_record
            source = record.source
            evidence_items.append({
                "evidence_id": evidence.id,
                "role": link.role,
                "note": link.note,
                "attribute_name": evidence.attribute_name,
                "observed_value": evidence.observed_value,
                "assessment": evidence.assessment,
                "review_status": evidence.review_status,
                "source_record_id": record.id,
                "source_name": source.name,
                "record_url": record.record_url,
                "external_id": record.external_id,
            })
        items.append({
            "id": conflict.id,
            "conflict_type": conflict.conflict_type,
            "status": conflict.status,
            "severity": conflict.severity,
            "attribute_name": conflict.attribute_name,
            "resolution": conflict.resolution,
            "resolution_reason": conflict.resolution_reason,
            "created_at": conflict.created_at.isoformat() if conflict.created_at else None,
            "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
            "evidence": evidence_items,
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def get_conflict_detail(session: Session, conflict_id: str) -> dict | None:
    """Return one conflict with its evidence and source snapshot metadata, read-only."""
    stmt = (
        select(Conflict)
        .where(Conflict.id == conflict_id)
        .options(
            selectinload(Conflict.evidence_links)
            .joinedload(ConflictEvidence.evidence)
            .joinedload(Evidence.source_record)
            .joinedload(SourceRecord.source)
        )
    )
    conflict = session.scalars(stmt).unique().one_or_none()
    if conflict is None:
        return None

    evidence_items = []
    for link in sorted(conflict.evidence_links, key=lambda item: item.evidence_id):
        evidence = link.evidence
        record = evidence.source_record
        source = record.source
        evidence_items.append({
            "evidence_id": evidence.id,
            "role": link.role,
            "note": link.note,
            "attribute_name": evidence.attribute_name,
            "observed_value": evidence.observed_value,
            "evidence_type": evidence.evidence_type,
            "assessment": evidence.assessment,
            "review_status": evidence.review_status,
            "evidence_notes": evidence.notes,
            "source_record_id": record.id,
            "source_name": source.name,
            "source_type": source.source_type,
            "source_url": source.base_url,
            "source_publisher": source.publisher,
            "source_is_official": source.is_official,
            "record_url": record.record_url,
            "external_id": record.external_id,
            "record_type": record.record_type,
            "content_hash": record.content_hash,
            "retrieved_at": record.retrieved_at.isoformat() if record.retrieved_at else None,
        })
    return {
        "id": conflict.id,
        "conflict_type": conflict.conflict_type,
        "status": conflict.status,
        "severity": conflict.severity,
        "attribute_name": conflict.attribute_name,
        "resolution": conflict.resolution,
        "resolution_reason": conflict.resolution_reason,
        "created_at": conflict.created_at.isoformat() if conflict.created_at else None,
        "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
        "evidence": evidence_items,
    }

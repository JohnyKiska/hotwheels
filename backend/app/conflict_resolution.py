"""Explicit, auditable resolution of catalog conflicts.

This service records a human decision without changing source evidence or
silently selecting a winning claim. The caller owns the transaction.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    ChangeLog, ChangeLogEvidence, Conflict, ConflictEvidence, Evidence, utc_now,
)

FINAL_STATUSES = {"resolved", "accepted_difference"}
ALLOWED_ACTOR_TYPES = {"human", "system"}


class UnknownConflict(LookupError):
    """Raised when the requested conflict does not exist."""


class InvalidConflictResolution(ValueError):
    """Raised when a resolution request is incomplete or unsafe."""


def resolve_conflict(
    session: Session,
    *,
    conflict_id: str,
    status: str,
    resolution: str,
    reason: str,
    actor_type: str = "human",
    actor_id: str | None = None,
    evidence_ids: list[str] | tuple[str, ...] = (),
) -> Conflict:
    """Resolve a conflict and append an audit entry; caller owns transaction.

    Final statuses are resolved and accepted_difference. Both a concise
    resolution and a reason are required. Cited evidence must already be linked
    to this conflict. Evidence rows and catalog entity statuses are not changed.
    Re-resolving a final conflict is rejected rather than overwriting a decision.
    """
    if status not in FINAL_STATUSES:
        raise InvalidConflictResolution(
            "status must be 'resolved' or 'accepted_difference'"
        )
    if not isinstance(resolution, str) or not resolution.strip():
        raise InvalidConflictResolution("resolution must not be blank")
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidConflictResolution("reason must not be blank")
    if actor_type not in ALLOWED_ACTOR_TYPES:
        raise InvalidConflictResolution("actor_type must be 'human' or 'system'")

    conflict = session.get(Conflict, conflict_id)
    if conflict is None:
        raise UnknownConflict(f"Conflict {conflict_id!r} does not exist")
    if conflict.status not in {"open", "under_review"}:
        raise InvalidConflictResolution(
            f"Conflict is already final (status={conflict.status!r})"
        )

    requested_evidence_ids = list(dict.fromkeys(evidence_ids))
    if requested_evidence_ids:
        linked_ids = set(
            session.scalars(
                select(ConflictEvidence.evidence_id).where(
                    ConflictEvidence.conflict_id == conflict.id,
                    ConflictEvidence.evidence_id.in_(requested_evidence_ids),
                )
            ).all()
        )
        if set(requested_evidence_ids) - linked_ids:
            raise InvalidConflictResolution(
                "Every cited evidence item must already be linked to this conflict"
            )
        existing_ids = set(
            session.scalars(
                select(Evidence.id).where(Evidence.id.in_(requested_evidence_ids))
            ).all()
        )
        if existing_ids != set(requested_evidence_ids):
            raise InvalidConflictResolution("One or more evidence items do not exist")

    old_values = {
        "status": conflict.status,
        "resolution": conflict.resolution,
        "resolution_reason": conflict.resolution_reason,
        "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
    }
    conflict.status = status
    conflict.resolution = resolution.strip()
    conflict.resolution_reason = reason.strip()
    conflict.resolved_at = utc_now()

    change = ChangeLog(
        entity_type="conflict",
        entity_id=conflict.id,
        action="resolve_conflict",
        old_values=old_values,
        new_values={
            "status": conflict.status,
            "resolution": conflict.resolution,
            "resolution_reason": conflict.resolution_reason,
            "resolved_at": conflict.resolved_at.isoformat(),
        },
        reason=reason.strip(),
        actor_type=actor_type,
        actor_id=actor_id,
    )
    session.add(change)
    session.flush()

    for evidence_id in requested_evidence_ids:
        session.add(
            ChangeLogEvidence(
                change_log_id=change.id,
                evidence_id=evidence_id,
                role="justification",
                note="Evidence explicitly cited in the conflict resolution.",
            )
        )
    session.flush()
    return conflict

def revise_conflict_resolution(
    session: Session,
    *,
    conflict_id: str,
    status: str,
    resolution: str,
    reason: str,
    actor_type: str = "human",
    actor_id: str | None = None,
    evidence_ids: list[str] | tuple[str, ...] = (),
) -> Conflict:
    """Revise a final decision while preserving every prior audit event.

    Only an explicit revision action can change a final conflict. The previous
    decision remains in its original ChangeLog row; this function appends a new
    event containing both the old and new values. The caller owns the transaction.
    """
    if status not in FINAL_STATUSES:
        raise InvalidConflictResolution(
            "status must be 'resolved' or 'accepted_difference'"
        )
    if not isinstance(resolution, str) or not resolution.strip():
        raise InvalidConflictResolution("resolution must not be blank")
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidConflictResolution("revision reason must not be blank")
    if actor_type not in ALLOWED_ACTOR_TYPES:
        raise InvalidConflictResolution("actor_type must be 'human' or 'system'")

    conflict = session.get(Conflict, conflict_id)
    if conflict is None:
        raise UnknownConflict(f"Conflict {conflict_id!r} does not exist")
    if conflict.status not in FINAL_STATUSES:
        raise InvalidConflictResolution(
            "Only a final conflict resolution can be revised"
        )

    requested_evidence_ids = list(dict.fromkeys(evidence_ids))
    if requested_evidence_ids:
        linked_ids = set(
            session.scalars(
                select(ConflictEvidence.evidence_id).where(
                    ConflictEvidence.conflict_id == conflict.id,
                    ConflictEvidence.evidence_id.in_(requested_evidence_ids),
                )
            ).all()
        )
        if set(requested_evidence_ids) - linked_ids:
            raise InvalidConflictResolution(
                "Every cited evidence item must already be linked to this conflict"
            )
        existing_ids = set(
            session.scalars(
                select(Evidence.id).where(Evidence.id.in_(requested_evidence_ids))
            ).all()
        )
        if existing_ids != set(requested_evidence_ids):
            raise InvalidConflictResolution("One or more evidence items do not exist")

    old_values = {
        "status": conflict.status,
        "resolution": conflict.resolution,
        "resolution_reason": conflict.resolution_reason,
        "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
    }
    conflict.status = status
    conflict.resolution = resolution.strip()
    conflict.resolution_reason = reason.strip()
    conflict.resolved_at = utc_now()

    change = ChangeLog(
        entity_type="conflict",
        entity_id=conflict.id,
        action="revise_conflict_resolution",
        old_values=old_values,
        new_values={
            "status": conflict.status,
            "resolution": conflict.resolution,
            "resolution_reason": conflict.resolution_reason,
            "resolved_at": conflict.resolved_at.isoformat(),
        },
        reason=reason.strip(),
        actor_type=actor_type,
        actor_id=actor_id,
    )
    session.add(change)
    session.flush()

    for evidence_id in requested_evidence_ids:
        session.add(
            ChangeLogEvidence(
                change_log_id=change.id,
                evidence_id=evidence_id,
                role="justification",
                note="Evidence explicitly cited in the conflict resolution revision.",
            )
        )
    session.flush()
    return conflict


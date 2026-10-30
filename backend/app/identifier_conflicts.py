"""Detection and traceability of identifiers shared by distinct releases.

A collision is a review signal, not an identity rule: releases are never merged
or confirmed automatically.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    CatalogIdentifier, Conflict, ConflictEvidence, ConflictRelease,
    Evidence, EvidenceRelease, IdentifierType, ReleaseIdentifier,
)
from .identifier_normalization import normalize_identifier



def create_identifier_collision_conflicts(session: Session) -> list[Conflict]:
    """Create/reconcile conflicts for identifiers assigned to two or more releases.

    Existing conflicts are backfilled with release/evidence links as well, so
    repeated runs are idempotent and can repair older incomplete conflict rows.
    The caller owns the transaction.
    """
    rows = session.execute(
        select(
            CatalogIdentifier.id,
            CatalogIdentifier.value,
            IdentifierType.code,
            ReleaseIdentifier.release_id,
        )
        .join(IdentifierType, CatalogIdentifier.identifier_type_id == IdentifierType.id)
        .join(ReleaseIdentifier, ReleaseIdentifier.identifier_id == CatalogIdentifier.id)
        .order_by(CatalogIdentifier.id, ReleaseIdentifier.release_id)
    ).all()

    releases_by_identifier: dict[str, set[str]] = {}
    details: dict[str, tuple[str, str]] = {}
    for identifier_id, value, type_code, release_id in rows:
        releases_by_identifier.setdefault(identifier_id, set()).add(release_id)
        details[identifier_id] = (type_code, value)

    created: list[Conflict] = []
    for identifier_id, release_ids in releases_by_identifier.items():
        if len(release_ids) < 2:
            continue
        type_code, value = details[identifier_id]
        conflict_key = f"{type_code}:{value}"
        conflict = session.scalar(
            select(Conflict).where(
                Conflict.conflict_type == "identifier_collision",
                Conflict.attribute_name == conflict_key,
            ).order_by(Conflict.created_at.asc(), Conflict.id.asc())
        )
        if conflict is None:
            conflict = Conflict(
                conflict_type="identifier_collision",
                status="open",
                severity="high",
                attribute_name=conflict_key,
            )
            session.add(conflict)
            session.flush()
            created.append(conflict)

        linked_release_ids = set(session.scalars(
            select(ConflictRelease.release_id).where(
                ConflictRelease.conflict_id == conflict.id
            )
        ).all())
        for release_id in sorted(release_ids - linked_release_ids):
            session.add(ConflictRelease(
                conflict_id=conflict.id,
                release_id=release_id,
                role="affected",
                note="Release is assigned the colliding catalog identifier.",
            ))

        # Attach source observations about this identifier for each affected release.
        evidence_rows = session.execute(
            select(Evidence.id, EvidenceRelease.release_id, Evidence.observed_value)
            .join(EvidenceRelease, EvidenceRelease.evidence_id == Evidence.id)
            .where(
                EvidenceRelease.release_id.in_(release_ids),
                Evidence.attribute_name == f"identifier:{type_code}",
            )
            .order_by(Evidence.id, EvidenceRelease.release_id)
        ).all()
        linked_evidence_ids = set(session.scalars(
            select(ConflictEvidence.evidence_id).where(
                ConflictEvidence.conflict_id == conflict.id
            )
        ).all())
        for evidence_id, release_id, observed_value in evidence_rows:
            # Evidence is scoped to an attribute and release, not to a specific
            # CatalogIdentifier row, so compare normalized values before linking.
            try:
                matches_identifier = (
                    observed_value is not None
                    and normalize_identifier(type_code, observed_value)
                    == normalize_identifier(type_code, value)
                )
            except ValueError:
                matches_identifier = False
            if matches_identifier and evidence_id not in linked_evidence_ids:
                session.add(ConflictEvidence(
                    conflict_id=conflict.id,
                    evidence_id=evidence_id,
                    role="identifier_observation",
                    note=f"Identifier observation linked to affected release {release_id}.",
                ))
                linked_evidence_ids.add(evidence_id)

    session.flush()
    return created

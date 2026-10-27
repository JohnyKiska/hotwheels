"""Detect disagreements between source claims about the same catalog entity.

A disagreement is a review signal only. This service never selects a winning
source, changes evidence assessments, or changes entity identity/status.
"""
from __future__ import annotations

import hashlib
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from .identifier_normalization import InvalidIdentifier, normalize_identifier
from .models import (
    Conflict,
    ConflictEvidence,
    Evidence,
    EvidenceCasting,
    EvidenceCastingVariant,
    EvidenceRelease,
    EvidenceSeries,
)


_ENTITY_LINKS = {
    "casting": (EvidenceCasting, EvidenceCasting.casting_id),
    "casting_variant": (
        EvidenceCastingVariant,
        EvidenceCastingVariant.casting_variant_id,
    ),
    "release": (EvidenceRelease, EvidenceRelease.release_id),
    "series": (EvidenceSeries, EvidenceSeries.series_id),
}


def _normalize_claim(attribute_name: str, value: str) -> str:
    """Normalize for comparison without discarding meaningful punctuation."""
    if attribute_name.startswith("identifier:"):
        type_code = attribute_name.split(":", 1)[1].strip()
        try:
            return normalize_identifier(type_code, value)
        except InvalidIdentifier:
            # Malformed identifiers still remain visible as distinct claims.
            pass
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def detect_evidence_disagreements(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    attribute_name: str | None = None,
) -> list[Conflict]:
    """Create/reuse open conflicts for distinct claims on one entity attribute.

    Evidence marked rejected and blank observations are ignored. Each conflict
    is keyed by entity, attribute, and the set of normalized observed values, so
    reruns are idempotent while a genuinely new claim set gets its own conflict.
    The caller owns the transaction; this function only flushes.
    """
    if entity_type not in _ENTITY_LINKS:
        raise ValueError(
            f"Unsupported entity_type {entity_type!r}; expected one of "
            f"{', '.join(sorted(_ENTITY_LINKS))}"
        )

    link_model, entity_fk = _ENTITY_LINKS[entity_type]
    stmt = (
        select(Evidence)
        .join(link_model, link_model.evidence_id == Evidence.id)
        .where(
            entity_fk == entity_id,
            Evidence.review_status != "rejected",
            Evidence.observed_value.is_not(None),
        )
        .order_by(Evidence.id)
    )
    if attribute_name is not None:
        stmt = stmt.where(Evidence.attribute_name == attribute_name)

    evidence_rows = session.scalars(stmt).all()
    claims_by_attribute: dict[str, dict[str, list[Evidence]]] = {}
    for evidence in evidence_rows:
        value = evidence.observed_value
        if value is None or not value.strip():
            continue
        normalized = _normalize_claim(evidence.attribute_name, value)
        claims_by_attribute.setdefault(evidence.attribute_name, {}).setdefault(
            normalized, []
        ).append(evidence)

    created_or_reused: list[Conflict] = []
    for attr, claims in sorted(claims_by_attribute.items()):
        if len(claims) < 2:
            continue

        normalized_values = sorted(claims)
        signature = "\n".join(
            [entity_type, entity_id, attr, *normalized_values]
        )
        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:32]
        conflict_key = f"evidence_disagreement:{digest}"
        conflict = session.scalar(
            select(Conflict).where(
                Conflict.conflict_type == "evidence_disagreement",
                Conflict.attribute_name == conflict_key,
            )
        )
        if conflict is None:
            identifier_attribute = attr.startswith("identifier:")
            conflict = Conflict(
                conflict_type="evidence_disagreement",
                status="open",
                severity="high" if identifier_attribute else "medium",
                attribute_name=conflict_key,
            )
            session.add(conflict)
            session.flush()

        linked_ids = set(
            session.scalars(
                select(ConflictEvidence.evidence_id).where(
                    ConflictEvidence.conflict_id == conflict.id
                )
            ).all()
        )
        for normalized_value in normalized_values:
            for evidence in claims[normalized_value]:
                if evidence.id in linked_ids:
                    continue
                session.add(
                    ConflictEvidence(
                        conflict_id=conflict.id,
                        evidence_id=evidence.id,
                        role="conflicting_claim",
                        note=(
                            f"Observed claim for {attr!r}; normalized value "
                            "disagrees with another non-rejected source claim."
                        ),
                    )
                )
                linked_ids.add(evidence.id)
        created_or_reused.append(conflict)

    session.flush()
    return created_or_reused

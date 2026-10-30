"""Register catalog identifiers and attach them to explicit catalog entities.

Registration is deliberately conservative: normalized equality reuses the
identifier row, but never merges catalog entities or confirms identity. When a
source record is supplied, the observed identifier is also recorded as evidence.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .identifier_conflicts import create_identifier_collision_conflicts
from .identifier_normalization import normalize_identifier
from .models import (
    CatalogIdentifier,
    ChangeLog,
    Casting,
    CastingIdentifier,
    CastingVariant,
    CastingVariantIdentifier,
    Evidence,
    EvidenceCasting,
    EvidenceCastingVariant,
    EvidenceRelease,
    IdentifierType,
    Release,
    ReleaseIdentifier,
    SourceRecord,
)

_ENTITY_CONFIG = {
    "release": (Release, ReleaseIdentifier, "release_id"),
    "casting": (Casting, CastingIdentifier, "casting_id"),
    "casting_variant": (CastingVariant, CastingVariantIdentifier, "casting_variant_id"),
}
_EVIDENCE_LINK_CONFIG = {
    "release": (EvidenceRelease, "release_id"),
    "casting": (EvidenceCasting, "casting_id"),
    "casting_variant": (EvidenceCastingVariant, "casting_variant_id"),
}


class UnknownIdentifierType(ValueError):
    """The identifier namespace has not been configured."""


class UnknownCatalogEntity(ValueError):
    """The target entity does not exist."""


class InvalidEntityType(ValueError):
    """The requested target type is not supported."""


class UnknownSourceRecord(ValueError):
    """The supplied source snapshot does not exist."""


def register_identifier(
    session: Session,
    *,
    type_code: str,
    value: str,
    entity_type: str,
    entity_id: str,
    role: str = "primary",
    source_note: str | None = None,
    notes: str | None = None,
    source_record_id: str | None = None,
    reason: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
) -> dict:
    """Create/reuse an identifier and link it to one existing catalog entity.

    The caller owns the transaction. The function flushes but does not commit.
    If source_record_id is supplied, a separate Evidence row records the exact
    observed value and links it to both that source snapshot and the target
    entity. Repeated registrations may reuse the canonical identifier/link,
    but each supplied source observation remains independently auditable.

    A release collision creates/reuses a review conflict; it never merges
    releases or changes their status.
    """
    if actor_type not in {"human", "system"}:
        raise ValueError("actor_type must be 'human' or 'system'")

    code = type_code.strip().casefold() if isinstance(type_code, str) else type_code
    normalized = normalize_identifier(code, value)

    if entity_type not in _ENTITY_CONFIG:
        raise InvalidEntityType(f"Unsupported catalog entity type: {entity_type}")

    source_record = None
    if source_record_id is not None:
        source_record = session.get(SourceRecord, source_record_id)
        if source_record is None:
            raise UnknownSourceRecord(f"Source record not found: {source_record_id}")

    entity_model, link_model, entity_fk = _ENTITY_CONFIG[entity_type]
    entity = session.get(entity_model, entity_id)
    if entity is None:
        raise UnknownCatalogEntity(f"{entity_type} not found: {entity_id}")

    identifier_type = session.scalar(
        select(IdentifierType).where(IdentifierType.code == code)
    )
    if identifier_type is None:
        raise UnknownIdentifierType(f"Unknown identifier type: {code}")

    identifier = session.scalar(
        select(CatalogIdentifier).where(
            CatalogIdentifier.identifier_type_id == identifier_type.id,
            CatalogIdentifier.normalized_value == normalized,
        )
    )
    identifier_created = identifier is None
    identifier_previous_notes = identifier.notes if identifier is not None else None
    identifier_notes_changed = False
    if identifier is None:
        identifier = CatalogIdentifier(
            identifier_type_id=identifier_type.id,
            value=value.strip(),
            normalized_value=normalized,
            notes=notes,
        )
        session.add(identifier)
        session.flush()
    elif notes and not identifier.notes:
        identifier.notes = notes
        identifier_notes_changed = True

    filters = {
        entity_fk: entity_id,
        "identifier_id": identifier.id,
    }
    link = session.get(link_model, tuple(filters.values()))
    link_created = link is None
    link_previous_role = link.role if link is not None else None
    link_previous_source_note = link.source_note if link is not None else None
    link_metadata_changed = False
    if link is None:
        link = link_model(
            **filters,
            role=role,
            source_note=source_note,
        )
        session.add(link)
    else:
        # Preserve existing provenance; only fill blank fields.
        if source_note and not link.source_note:
            link.source_note = source_note
            link_metadata_changed = True
        if role and not link.role:
            link.role = role
            link_metadata_changed = True

    evidence = None
    evidence_created = False
    evidence_link_created = False
    if source_record is not None:
        evidence_attribute = f"identifier:{code}"
        evidence_candidates = session.scalars(
            select(Evidence).where(
                Evidence.source_record_id == source_record.id,
                Evidence.attribute_name == evidence_attribute,
            )
        ).all()
        # A source snapshot is immutable input: reprocessing the same normalized
        # identifier claim must reuse its evidence, not mint a duplicate audit row.
        # A different SourceRecord remains a distinct observation even when the
        # identifier value is identical.
        evidence = next(
            (
                candidate for candidate in evidence_candidates
                if candidate.observed_value is not None
                and normalize_identifier(code, candidate.observed_value) == normalized
            ),
            None,
        )
        if evidence is None:
            evidence = Evidence(
                source_record_id=source_record.id,
                attribute_name=evidence_attribute,
                observed_value=value.strip(),
                evidence_type="text",
                assessment="supports",
                review_status="pending",
                notes="Identifier observed in source record; registration does not establish entity identity.",
            )
            session.add(evidence)
            session.flush()
            evidence_created = True

        evidence_link_model, evidence_fk = _EVIDENCE_LINK_CONFIG[entity_type]
        evidence_link = session.get(evidence_link_model, (evidence.id, entity_id))
        if evidence_link is None:
            session.add(evidence_link_model(
                evidence_id=evidence.id,
                **{evidence_fk: entity_id},
                role="identifier_observation",
            ))
            evidence_link_created = True

    session.flush()

    # Audit effective changes, newly observed source claims, and newly added
    # links between an existing claim and an entity. Exact retries are no-ops.
    if (identifier_created or link_created or identifier_notes_changed
            or link_metadata_changed or evidence_created or evidence_link_created):
        audit_reason = (reason or "").strip()
        if not audit_reason:
            audit_reason = (source_note or notes or "Identifier registration").strip()
        session.add(ChangeLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action="register_identifier",
            old_values={
                "identifier_exists": not identifier_created,
                "identifier_notes": identifier_previous_notes,
                "link_exists": not link_created,
                "link_role": link_previous_role,
                "link_source_note": link_previous_source_note,
            },
            new_values={
                "identifier_id": identifier.id,
                "identifier_type": code,
                "identifier_value": identifier.value,
                "normalized_value": identifier.normalized_value,
                "link_created": link_created,
                "role": link.role,
                "source_note": link.source_note,
                "source_record_id": source_record.id if source_record else None,
                "evidence_id": evidence.id if evidence else None,
                "identifier_created": identifier_created,
                "identifier_notes_changed": identifier_notes_changed,
                "link_metadata_changed": link_metadata_changed,
            },
            reason=audit_reason,
            actor_type=actor_type,
            actor_id=actor_id,
        ))
        session.flush()

    new_conflicts = []
    if entity_type == "release":
        new_conflicts = create_identifier_collision_conflicts(session)

    return {
        "identifier": identifier,
        "link": link,
        "identifier_created": identifier_created,
        "link_created": link_created,
        "evidence": evidence,
        "evidence_created": evidence_created,
        "evidence_link_created": evidence_link_created,
        "new_conflicts": new_conflicts,
    }

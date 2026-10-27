"""Register catalog identifiers and attach them to explicit catalog entities.

Registration is deliberately conservative: normalized equality reuses the
identifier row, but never merges catalog entities or confirms identity.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .identifier_conflicts import create_identifier_collision_conflicts
from .identifier_normalization import normalize_identifier
from .models import (
    CatalogIdentifier,
    Casting,
    CastingIdentifier,
    CastingVariant,
    CastingVariantIdentifier,
    IdentifierType,
    Release,
    ReleaseIdentifier,
)

_ENTITY_CONFIG = {
    "release": (Release, ReleaseIdentifier, "release_id"),
    "casting": (Casting, CastingIdentifier, "casting_id"),
    "casting_variant": (CastingVariant, CastingVariantIdentifier, "casting_variant_id"),
}


class UnknownIdentifierType(ValueError):
    """The identifier namespace has not been configured."""


class UnknownCatalogEntity(ValueError):
    """The target entity does not exist."""


class InvalidEntityType(ValueError):
    """The requested target type is not supported."""


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
) -> dict:
    """Create/reuse an identifier and link it to one existing catalog entity.

    The caller owns the transaction. The function flushes but does not commit.
    A release collision creates/reuses a review conflict; it never merges
    releases or changes their status.
    """
    code = type_code.strip().casefold() if isinstance(type_code, str) else type_code
    normalized = normalize_identifier(code, value)

    if entity_type not in _ENTITY_CONFIG:
        raise InvalidEntityType(f"Unsupported catalog entity type: {entity_type}")

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

    filters = {
        entity_fk: entity_id,
        "identifier_id": identifier.id,
    }
    link = session.get(link_model, tuple(filters.values()))
    link_created = link is None
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
        if role and not link.role:
            link.role = role

    session.flush()
    new_conflicts = []
    if entity_type == "release":
        new_conflicts = create_identifier_collision_conflicts(session)

    return {
        "identifier": identifier,
        "link": link,
        "identifier_created": identifier_created,
        "link_created": link_created,
        "new_conflicts": new_conflicts,
    }

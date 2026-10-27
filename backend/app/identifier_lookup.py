"""Read-only lookup of catalog entities linked to an identifier."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

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


def find_identifier_matches(session: Session, type_code: str, value: str) -> dict:
    """Find every entity linked to a namespace-aware identifier.

    Returned links are evidence for review, not proof of identity. This function
    never creates links, merges records, or changes conflict status.
    """
    code = type_code.strip().casefold() if isinstance(type_code, str) else type_code
    normalized = normalize_identifier(code, value)
    identifier_row = session.execute(
        select(CatalogIdentifier, IdentifierType)
        .join(IdentifierType, CatalogIdentifier.identifier_type_id == IdentifierType.id)
        .where(
            IdentifierType.code == code,
            CatalogIdentifier.normalized_value == normalized,
        )
    ).first()

    if identifier_row is None:
        return {"identifier": None, "matches": [], "ambiguous": False}

    identifier, identifier_type = identifier_row
    matches: list[dict] = []

    for link, entity in session.execute(
        select(ReleaseIdentifier, Release)
        .join(Release, ReleaseIdentifier.release_id == Release.id)
        .where(ReleaseIdentifier.identifier_id == identifier.id)
    ).all():
        matches.append({
            "entity_type": "release",
            "entity_id": entity.id,
            "name": entity.name,
            "catalog_year": entity.catalog_year,
            "status": entity.status,
            "relationship_role": link.role,
            "source_note": link.source_note,
        })

    for link, entity in session.execute(
        select(CastingIdentifier, Casting)
        .join(Casting, CastingIdentifier.casting_id == Casting.id)
        .where(CastingIdentifier.identifier_id == identifier.id)
    ).all():
        matches.append({
            "entity_type": "casting",
            "entity_id": entity.id,
            "name": entity.name,
            "catalog_year": None,
            "status": entity.status,
            "relationship_role": link.role,
            "source_note": link.source_note,
        })

    for link, entity in session.execute(
        select(CastingVariantIdentifier, CastingVariant)
        .join(CastingVariant, CastingVariantIdentifier.casting_variant_id == CastingVariant.id)
        .where(CastingVariantIdentifier.identifier_id == identifier.id)
    ).all():
        matches.append({
            "entity_type": "casting_variant",
            "entity_id": entity.id,
            "name": entity.name,
            "catalog_year": None,
            "status": entity.status,
            "relationship_role": link.role,
            "source_note": link.source_note,
        })

    release_ids = {item["entity_id"] for item in matches if item["entity_type"] == "release"}
    return {
        "identifier": {
            "id": identifier.id,
            "type_code": identifier_type.code,
            "label": identifier_type.label,
            "value": identifier.value,
            "normalized_value": identifier.normalized_value,
        },
        "matches": matches,
        "ambiguous": len(release_ids) > 1,
    }

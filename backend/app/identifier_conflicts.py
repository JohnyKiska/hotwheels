"""Detection of identifiers shared by distinct releases.

This is a review signal, not an identity rule: matching identifiers never merge
or confirm releases automatically.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CatalogIdentifier, Conflict, IdentifierType, ReleaseIdentifier


def create_identifier_collision_conflicts(session: Session) -> list[Conflict]:
    """Create open review conflicts for identifiers assigned to 2+ releases.

    The caller owns the transaction and should commit after reviewing the result.
    Repeated runs are idempotent while an existing conflict for that identifier
    remains in the database.
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
        existing = session.scalar(
            select(Conflict).where(
                Conflict.conflict_type == "identifier_collision",
                Conflict.attribute_name == conflict_key,
                Conflict.status.in_(("open", "under_review", "resolved", "accepted_difference")),
            )
        )
        if existing is not None:
            continue
        conflict = Conflict(
            conflict_type="identifier_collision",
            status="open",
            severity="high",
            attribute_name=conflict_key,
        )
        session.add(conflict)
        created.append(conflict)
    session.flush()
    return created

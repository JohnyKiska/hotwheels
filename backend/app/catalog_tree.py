"""Validation and audited operations for catalog-tree placements."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CatalogNode, ChangeLog


ALLOWED_CHILDREN = {
    "root": {"product_line", "year", "group", "theme", "series", "release", "package"},
    "product_line": {"year", "group", "theme", "series", "release", "package"},
    "year": {"group", "theme", "series", "release", "package"},
    "series": {"group", "theme", "release"},
    "group": {"group", "theme", "year", "series", "release", "package"},
    "theme": {"group", "theme", "series", "release", "package"},
    "release": set(),
    "package": set(),
}


def move_catalog_node(
    session: Session,
    node_id: str,
    new_parent_id: str | None,
    *,
    reason: str,
    sort_order: int | None = None,
    actor_type: str = "user",
    actor_id: str | None = None,
) -> CatalogNode:
    """Move a node safely and append an audit entry; caller owns the transaction."""
    node = session.get(CatalogNode, node_id)
    if node is None:
        raise ValueError(f"Catalog node not found: {node_id}")

    if node.node_type == "root" and new_parent_id is not None:
        raise ValueError("A root node cannot have a parent")
    if node.node_type != "root" and new_parent_id is None:
        raise ValueError("Only a root node may have no parent")

    parent = session.get(CatalogNode, new_parent_id) if new_parent_id else None
    if new_parent_id and parent is None:
        raise ValueError(f"Parent catalog node not found: {new_parent_id}")
    if parent is not None:
        if node.node_type not in ALLOWED_CHILDREN[parent.node_type]:
            raise ValueError(
                f"Node type {node.node_type!r} cannot be placed under {parent.node_type!r}"
            )

        # Walk up from the proposed parent. Encountering the node means the move
        # would create a cycle; the loop also catches pre-existing malformed cycles.
        ancestor_id = parent.id
        visited: set[str] = set()
        while ancestor_id is not None:
            if ancestor_id == node.id:
                raise ValueError("Moving this node would create a catalog-tree cycle")
            if ancestor_id in visited:
                raise ValueError("The existing catalog tree contains a cycle")
            visited.add(ancestor_id)
            ancestor = session.get(CatalogNode, ancestor_id)
            if ancestor is None:
                raise ValueError("The existing catalog tree contains a missing parent")
            ancestor_id = ancestor.parent_id

    old_parent_id = node.parent_id
    old_sort_order = node.sort_order
    new_sort_order = old_sort_order if sort_order is None else sort_order
    if new_sort_order < 0:
        raise ValueError("sort_order must be zero or greater")

    if old_parent_id == new_parent_id and old_sort_order == new_sort_order:
        return node

    node.parent_id = new_parent_id
    node.sort_order = new_sort_order
    session.add(
        ChangeLog(
            entity_type="catalog_node",
            entity_id=node.id,
            action="moved",
            old_values={"parent_id": old_parent_id, "sort_order": old_sort_order},
            new_values={"parent_id": new_parent_id, "sort_order": new_sort_order},
            reason=reason,
            actor_type=actor_type,
            actor_id=actor_id,
        )
    )
    session.flush()
    return node

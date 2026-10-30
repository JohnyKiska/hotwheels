"""Read and safely move catalog-tree placements through the public API."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalog_tree import move_catalog_node
from .db import get_db
from .models import CatalogNode

router = APIRouter(prefix="/catalog", tags=["catalog"])


class MoveCatalogNodeRequest(BaseModel):
    new_parent_id: str | None
    reason: str = Field(min_length=1, max_length=2000)
    sort_order: int | None = Field(default=None, ge=0)
    actor_type: str = Field(default="user", min_length=1, max_length=40)
    actor_id: str | None = Field(default=None, max_length=160)


def _node_label(node: CatalogNode) -> str:
    if node.label_override:
        return node.label_override
    if node.node_type == "year":
        return str(node.catalog_year) if node.catalog_year is not None else "Year unknown"
    if node.node_type == "product_line" and node.product_line:
        return node.product_line.name
    if node.node_type == "series" and node.series:
        return node.series.name
    if node.node_type == "release" and node.release:
        return node.release.name or node.release.casting.name
    if node.node_type == "package" and node.package:
        return node.package.name or "Package"
    return {"root": "Catalog", "group": "Group", "theme": "Theme"}.get(
        node.node_type, node.node_type.replace("_", " ").title()
    )


def _serialize_node(node: CatalogNode, children: list[dict]) -> dict:
    return {
        "id": node.id,
        "node_type": node.node_type,
        "label": _node_label(node),
        "status": node.status,
        "sort_order": node.sort_order,
        "catalog_year": node.catalog_year,
        "parent_id": node.parent_id,
        "product_line_id": node.product_line_id,
        "series_id": node.series_id,
        "release_id": node.release_id,
        "package_id": node.package_id,
        "children": children,
    }


@router.get("/tree")
def get_catalog_tree(
    parent_id: str | None = None,
    session: Session = Depends(get_db),
) -> dict:
    """Return roots or a selected node's subtree, ordered deterministically."""
    if parent_id is not None and session.get(CatalogNode, parent_id) is None:
        raise HTTPException(status_code=404, detail="Catalog node not found")

    nodes = session.scalars(
        select(CatalogNode).order_by(CatalogNode.sort_order, CatalogNode.id)
    ).all()
    by_parent: dict[str | None, list[CatalogNode]] = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    def build(node: CatalogNode, path: frozenset[str]) -> dict:
        # Defensive guard against corrupted legacy data; normal writes reject cycles.
        if node.id in path:
            raise HTTPException(status_code=409, detail="Catalog tree contains a cycle")
        next_path = path | {node.id}
        children = [
            build(child, next_path)
            for child in by_parent.get(node.id, [])
            if child.status != "hidden"
        ]
        return _serialize_node(node, children)

    if parent_id is not None:
        selected = session.get(CatalogNode, parent_id)
        return {"items": [build(selected, frozenset())]}
    roots = [node for node in by_parent.get(None, []) if node.status != "hidden"]
    return {"items": [build(root, frozenset()) for root in roots]}


@router.post("/nodes/{node_id}/move")
def post_catalog_node_move(
    node_id: str,
    request: MoveCatalogNodeRequest,
    session: Session = Depends(get_db),
) -> dict:
    """Move a placement without changing the linked Release/Series identity."""
    try:
        node = move_catalog_node(
            session,
            node_id,
            request.new_parent_id,
            reason=request.reason,
            sort_order=request.sort_order,
            actor_type=request.actor_type,
            actor_id=request.actor_id,
        )
        session.commit()
        session.refresh(node)
    except ValueError as exc:
        session.rollback()
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 422
        raise HTTPException(status_code=status_code, detail=message) from exc
    except Exception:
        session.rollback()
        raise
    return _serialize_node(node, [])

"""Permission-protected catalog administration endpoints."""
from __future__ import annotations

import unicodedata
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .account_api import _require_csrf, _require_permission
from .db import get_db
from .models import (
    CatalogIdentifier,
    Casting,
    CastingVariant,
    ChangeLog,
    Evidence,
    EvidenceProductLine,
    IdentifierType,
    ProductLine,
    Release,
    ReleaseIdentifier,
    ReleaseProductLine,
    ReleaseSeries,
    Series,
    User,
)

router = APIRouter(prefix="/api/v1/admin/catalog", tags=["admin-catalog"])

CastingStatus = Literal["candidate", "under_review", "confirmed", "rejected"]


class CastingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    first_known_year: int | None = Field(default=None, ge=1968, le=2100)
    status: CastingStatus | None = None
    reason: str = Field(min_length=1, max_length=4000)


def _casting_payload(casting: Casting) -> dict:
    return {
        "id": casting.id,
        "name": casting.name,
        "description": casting.description,
        "first_known_year": casting.first_known_year,
        "status": casting.status,
        "created_at": casting.created_at.isoformat(),
        "updated_at": casting.updated_at.isoformat(),
    }


@router.get("/castings")
def list_castings(
    q: str | None = Query(default=None, max_length=240),
    status: CastingStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    """Search and paginate casting identities."""
    filters = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters.append(or_(Casting.name.ilike(term), Casting.description.ilike(term)))
    if status:
        filters.append(Casting.status == status)

    total = db.scalar(select(func.count(Casting.id)).where(*filters)) or 0
    rows = db.scalars(
        select(Casting)
        .where(*filters)
        .order_by(func.lower(Casting.name), Casting.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [_casting_payload(item) for item in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/castings/{casting_id}")
def get_casting(
    casting_id: str,
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    casting = db.get(Casting, casting_id)
    if casting is None:
        raise HTTPException(status_code=404, detail="Casting not found.")
    payload = _casting_payload(casting)
    payload["variants"] = [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "status": item.status,
        }
        for item in sorted(casting.variants, key=lambda item: (item.name or "", item.id))
    ]
    payload["releases_count"] = len(casting.releases)
    return payload


@router.patch("/castings/{casting_id}")
def patch_casting(
    casting_id: str,
    body: CastingPatch,
    request: Request,
    user: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    """Update editable casting fields and append a ChangeLog entry atomically."""
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty change reason is required.")

    changes = body.model_dump(exclude_unset=True)
    changes.pop("reason", None)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one casting field must be supplied.")
    if "name" in changes and (changes["name"] is None or not changes["name"].strip()):
        raise HTTPException(status_code=422, detail="Casting name cannot be empty.")
    if "status" in changes and changes["status"] is None:
        raise HTTPException(status_code=422, detail="Casting status cannot be null.")
    if "name" in changes:
        changes["name"] = changes["name"].strip()

    casting = db.get(Casting, casting_id)
    if casting is None:
        raise HTTPException(status_code=404, detail="Casting not found.")

    old_values = {}
    new_values = {}
    for field, value in changes.items():
        current = getattr(casting, field)
        if current != value:
            old_values[field] = current
            new_values[field] = value
    if not new_values:
        return _casting_payload(casting)

    try:
        for field, value in new_values.items():
            setattr(casting, field, value)
        db.add(ChangeLog(
            entity_type="casting",
            entity_id=casting.id,
            action="update",
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_type="user",
            actor_id=user.id,
        ))
        db.commit()
        db.refresh(casting)
    except Exception:
        db.rollback()
        raise
    return _casting_payload(casting)


def _release_payload(
    release: Release, identifiers: list[dict[str, str]] | None = None
) -> dict:
    return {
        "id": release.id,
        "casting_id": release.casting_id,
        "casting_name": release.casting.name if release.casting else None,
        "casting_variant_id": release.casting_variant_id,
        "casting_variant_name": release.casting_variant.name if release.casting_variant else None,
        "catalog_year": release.catalog_year,
        "name": release.name,
        "assortment_number": release.assortment_number,
        "description": release.description,
        "status": release.status,
        "identifiers": identifiers or [],
        "series": [
            {"id": item.id, "name": item.name}
            for item in sorted(release.series, key=lambda item: (item.name.lower(), item.id))
        ],
        "product_lines": [
            {
                "id": link.product_line.id,
                "code": link.product_line.code,
                "name": link.product_line.name,
                "status": link.product_line.status,
                "membership_status": link.membership_status,
            }
            for link in sorted(
                release.product_line_links,
                key=lambda item: (item.product_line.code.casefold(), item.product_line.id),
            )
        ],
        "created_at": release.created_at.isoformat(),
        "updated_at": release.updated_at.isoformat(),
    }


def _release_identifiers(
    db: Session, release_ids: list[str]
) -> dict[str, list[dict[str, str]]]:
    if not release_ids:
        return {}

    links = db.scalars(
        select(ReleaseIdentifier)
        .where(ReleaseIdentifier.release_id.in_(release_ids))
        .options(
            selectinload(ReleaseIdentifier.identifier).selectinload(
                CatalogIdentifier.identifier_type
            )
        )
    ).all()
    identifiers_by_release: dict[str, list[dict[str, str]]] = {}
    for link in links:
        identifiers_by_release.setdefault(link.release_id, []).append(
            {
                "value": link.identifier.value,
                "type_code": link.identifier.identifier_type.code,
                "role": link.role,
            }
        )
    for identifiers in identifiers_by_release.values():
        identifiers.sort(
            key=lambda item: (
                item["type_code"],
                item["value"].casefold(),
                item["role"],
            )
        )
    return identifiers_by_release


@router.get("/releases")
def list_releases(
    q: str | None = Query(default=None, max_length=240),
    casting_id: str | None = Query(default=None, max_length=36),
    catalog_year: int | None = Query(default=None, ge=1968, le=2100),
    status: CastingStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    """Search and paginate releases without mutating catalog data."""
    filters = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        identifier_match = (
            select(1)
            .select_from(ReleaseIdentifier)
            .join(
                CatalogIdentifier,
                CatalogIdentifier.id == ReleaseIdentifier.identifier_id,
            )
            .join(
                IdentifierType,
                IdentifierType.id == CatalogIdentifier.identifier_type_id,
            )
            .where(
                ReleaseIdentifier.release_id == Release.id,
                IdentifierType.code.in_(("sku", "upc")),
                CatalogIdentifier.value.ilike(term),
            )
            .exists()
        )
        filters.append(or_(
            Release.name.ilike(term),
            Release.assortment_number.ilike(term),
            Casting.name.ilike(term),
            identifier_match,
        ))
    if casting_id:
        filters.append(Release.casting_id == casting_id)
    if catalog_year is not None:
        filters.append(Release.catalog_year == catalog_year)
    if status:
        filters.append(Release.status == status)

    statement = select(Release).outerjoin(Casting, Casting.id == Release.casting_id).where(*filters)
    total = db.scalar(
        select(func.count(Release.id))
        .outerjoin(Casting, Casting.id == Release.casting_id)
        .where(*filters)
    ) or 0
    rows = db.scalars(
        statement.options(
            selectinload(Release.casting),
            selectinload(Release.casting_variant),
            selectinload(Release.series),
            selectinload(Release.product_line_links).selectinload(
                ReleaseProductLine.product_line
            ),
        )
        .order_by(Release.catalog_year.desc().nullslast(), Release.name, Release.id)
        .limit(limit)
        .offset(offset)
    ).all()
    identifiers_by_release = _release_identifiers(db, [item.id for item in rows])
    return {
        "items": [
            _release_payload(item, identifiers_by_release.get(item.id, []))
            for item in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/releases/{release_id}")
def get_release(
    release_id: str,
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    release = db.scalar(
        select(Release)
        .where(Release.id == release_id)
        .options(
            selectinload(Release.casting),
            selectinload(Release.casting_variant),
            selectinload(Release.series),
            selectinload(Release.product_line_links).selectinload(
                ReleaseProductLine.product_line
            ),
        )
    )
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found.")
    identifiers = _release_identifiers(db, [release.id]).get(release.id, [])
    return _release_payload(release, identifiers)


class ReleasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    casting_id: str | None = Field(default=None, max_length=36)
    casting_variant_id: str | None = Field(default=None, max_length=36)
    catalog_year: int | None = Field(default=None, ge=1968, le=2100)
    name: str | None = Field(default=None, max_length=240)
    assortment_number: str | None = Field(default=None, max_length=80)
    description: str | None = None
    status: CastingStatus | None = None
    reason: str = Field(min_length=1, max_length=4000)


class CastingVariantPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=240)
    description: str | None = None
    status: CastingStatus | None = None
    reason: str = Field(min_length=1, max_length=4000)


def _apply_audited_patch(db: Session, *, entity, entity_type: str, changes: dict,
                         reason: str, user: User) -> dict:
    old_values = {}
    new_values = {}
    for field, value in changes.items():
        if isinstance(value, str) and field in {"name", "assortment_number"}:
            value = value.strip() or None
        current = getattr(entity, field)
        if current != value:
            old_values[field] = current
            new_values[field] = value
    if not new_values:
        return {}
    for field, value in new_values.items():
        setattr(entity, field, value)
    db.add(ChangeLog(
        entity_type=entity_type,
        entity_id=entity.id,
        action="update",
        old_values=old_values,
        new_values=new_values,
        reason=reason,
        actor_type="user",
        actor_id=user.id,
    ))
    return new_values


@router.patch("/releases/{release_id}")
def patch_release(
    release_id: str,
    body: ReleasePatch,
    request: Request,
    user: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    """Update release metadata and its selected variant with an atomic audit event."""
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty change reason is required.")
    changes = body.model_dump(exclude_unset=True)
    changes.pop("reason", None)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one release field must be supplied.")
    if "status" in changes and changes["status"] is None:
        raise HTTPException(status_code=422, detail="Release status cannot be null.")
    release = db.scalar(
        select(Release).where(Release.id == release_id).options(
            selectinload(Release.casting),
            selectinload(Release.casting_variant),
            selectinload(Release.series),
            selectinload(Release.product_line_links).selectinload(
                ReleaseProductLine.product_line
            ),
        )
    )
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found.")

    from .models import CastingVariant
    effective_casting_id = changes.get("casting_id", release.casting_id)
    if "casting_id" in changes and effective_casting_id is not None:
        if db.get(Casting, effective_casting_id) is None:
            raise HTTPException(status_code=422, detail="Casting not found.")

    if "casting_variant_id" in changes:
        if changes["casting_variant_id"] is not None:
            variant = db.get(CastingVariant, changes["casting_variant_id"])
            if effective_casting_id is None:
                raise HTTPException(status_code=422, detail="A variant requires a release casting.")
            if variant is None or variant.casting_id != effective_casting_id:
                raise HTTPException(status_code=422, detail="Variant must belong to the release casting.")
        # Explicit null means the caller intentionally clears the variant.
    else:
        current_variant_id = release.casting_variant_id
        if current_variant_id is not None:
            current_variant = db.get(CastingVariant, current_variant_id)
            if effective_casting_id is None or current_variant is None or current_variant.casting_id != effective_casting_id:
                raise HTTPException(
                    status_code=422,
                    detail="Explicitly clear or replace casting_variant_id when changing or removing the casting.",
                )
    try:
        _apply_audited_patch(
            db, entity=release, entity_type="release", changes=changes,
            reason=reason, user=user,
        )
        db.commit()
        db.refresh(release)
    except Exception:
        db.rollback()
        raise
    identifiers = _release_identifiers(db, [release.id]).get(release.id, [])
    return _release_payload(release, identifiers)


@router.patch("/variants/{variant_id}")
def patch_casting_variant(
    variant_id: str,
    body: CastingVariantPatch,
    request: Request,
    user: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    """Update variant metadata without changing its parent casting."""
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty change reason is required.")
    changes = body.model_dump(exclude_unset=True)
    changes.pop("reason", None)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one variant field must be supplied.")
    if "status" in changes and changes["status"] is None:
        raise HTTPException(status_code=422, detail="Variant status cannot be null.")

    from .models import CastingVariant
    variant = db.get(CastingVariant, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Casting variant not found.")
    try:
        _apply_audited_patch(
            db, entity=variant, entity_type="casting_variant", changes=changes,
            reason=reason, user=user,
        )
        db.commit()
        db.refresh(variant)
    except Exception:
        db.rollback()
        raise
    return {
        "id": variant.id,
        "casting_id": variant.casting_id,
        "name": variant.name,
        "description": variant.description,
        "status": variant.status,
        "updated_at": variant.updated_at.isoformat(),
    }


class CastingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=240)
    description: str | None = None
    first_known_year: int | None = Field(default=None, ge=1968, le=2100)
    status: CastingStatus = "candidate"
    reason: str = Field(min_length=1, max_length=4000)


class CastingVariantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=240)
    description: str | None = None
    status: CastingStatus = "candidate"
    reason: str = Field(min_length=1, max_length=4000)


class ReleaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    casting_id: str | None = Field(default=None, min_length=1, max_length=36)
    casting_variant_id: str | None = Field(default=None, max_length=36)
    catalog_year: int | None = Field(default=None, ge=1968, le=2100)
    name: str | None = Field(default=None, max_length=240)
    assortment_number: str | None = Field(default=None, max_length=80)
    description: str | None = None
    status: CastingStatus = "candidate"
    reason: str = Field(min_length=1, max_length=4000)


def _clean_optional_text(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def _variant_payload(variant: CastingVariant) -> dict:
    return {
        "id": variant.id,
        "casting_id": variant.casting_id,
        "name": variant.name,
        "description": variant.description,
        "status": variant.status,
        "created_at": variant.created_at.isoformat(),
        "updated_at": variant.updated_at.isoformat(),
    }


@router.post("/castings", status_code=201)
def create_casting(
    body: CastingCreate,
    request: Request,
    user: User = Depends(_require_permission("catalog.create")),
    db: Session = Depends(get_db),
) -> dict:
    """Create a casting and its audit event in one transaction."""
    _require_csrf(request)
    name = body.name.strip()
    reason = body.reason.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Casting name cannot be empty.")
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty creation reason is required.")

    casting = Casting(
        name=name,
        description=_clean_optional_text(body.description),
        first_known_year=body.first_known_year,
        status=body.status,
    )
    try:
        db.add(casting)
        db.flush()
        db.add(ChangeLog(
            entity_type="casting",
            entity_id=casting.id,
            action="create",
            old_values=None,
            new_values={
                "name": casting.name,
                "description": casting.description,
                "first_known_year": casting.first_known_year,
                "status": casting.status,
            },
            reason=reason,
            actor_type="user",
            actor_id=user.id,
        ))
        db.commit()
        db.refresh(casting)
    except Exception:
        db.rollback()
        raise
    return _casting_payload(casting)


@router.post("/castings/{casting_id}/variants", status_code=201)
def create_casting_variant(
    casting_id: str,
    body: CastingVariantCreate,
    request: Request,
    user: User = Depends(_require_permission("catalog.create")),
    db: Session = Depends(get_db),
) -> dict:
    """Create a construction variant under the selected casting."""
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty creation reason is required.")
    casting = db.get(Casting, casting_id)
    if casting is None:
        raise HTTPException(status_code=404, detail="Casting not found.")

    variant = CastingVariant(
        casting_id=casting.id,
        name=_clean_optional_text(body.name),
        description=_clean_optional_text(body.description),
        status=body.status,
    )
    try:
        db.add(variant)
        db.flush()
        db.add(ChangeLog(
            entity_type="casting_variant",
            entity_id=variant.id,
            action="create",
            old_values=None,
            new_values={
                "casting_id": variant.casting_id,
                "name": variant.name,
                "description": variant.description,
                "status": variant.status,
            },
            reason=reason,
            actor_type="user",
            actor_id=user.id,
        ))
        db.commit()
        db.refresh(variant)
    except Exception:
        db.rollback()
        raise
    return _variant_payload(variant)


@router.post("/releases", status_code=201)
def create_release(
    body: ReleaseCreate,
    request: Request,
    user: User = Depends(_require_permission("catalog.create")),
    db: Session = Depends(get_db),
) -> dict:
    """Create a release after validating its casting and optional variant."""
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty creation reason is required.")

    casting = db.get(Casting, body.casting_id) if body.casting_id is not None else None
    if body.casting_id is not None and casting is None:
        raise HTTPException(status_code=404, detail="Casting not found.")
    if body.casting_variant_id is not None:
        if casting is None:
            raise HTTPException(
                status_code=422,
                detail="A variant requires a release casting.",
            )
        variant = db.get(CastingVariant, body.casting_variant_id)
        if variant is None or variant.casting_id != casting.id:
            raise HTTPException(
                status_code=422,
                detail="Variant must belong to the release casting.",
            )

    release = Release(
        casting_id=casting.id if casting else None,
        casting_variant_id=body.casting_variant_id,
        catalog_year=body.catalog_year,
        name=_clean_optional_text(body.name),
        assortment_number=_clean_optional_text(body.assortment_number),
        description=_clean_optional_text(body.description),
        status=body.status,
    )
    try:
        db.add(release)
        db.flush()
        db.add(ChangeLog(
            entity_type="release",
            entity_id=release.id,
            action="create",
            old_values=None,
            new_values={
                "casting_id": release.casting_id,
                "casting_variant_id": release.casting_variant_id,
                "catalog_year": release.catalog_year,
                "name": release.name,
                "assortment_number": release.assortment_number,
                "description": release.description,
                "status": release.status,
            },
            reason=reason,
            actor_type="user",
            actor_id=user.id,
        ))
        db.commit()
        db.refresh(release)
        # Load relationships used by the standard release response.
        db.refresh(release, attribute_names=["casting", "casting_variant", "series"])
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A release with this casting, catalog year and assortment number may already exist.",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return _release_payload(release)


class SeriesCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=240)
    description: str | None = None
    series_type: str | None = Field(default=None, max_length=80)
    status: CastingStatus = "candidate"
    reason: str = Field(min_length=1, max_length=4000)


class SeriesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    series_type: str | None = Field(default=None, max_length=80)
    status: CastingStatus | None = None
    reason: str = Field(min_length=1, max_length=4000)


class ReleaseSeriesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_ids: list[str] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=4000)


def _series_payload(series: Series) -> dict:
    return {
        "id": series.id,
        "name": series.name,
        "description": series.description,
        "series_type": series.series_type,
        "status": series.status,
        "release_count": len(series.release_links),
        "created_at": series.created_at.isoformat(),
        "updated_at": series.updated_at.isoformat(),
    }


@router.get("/series")
def list_series(
    q: str | None = Query(default=None, max_length=240),
    status: CastingStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    filters = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters.append(or_(Series.name.ilike(term), Series.description.ilike(term),
                           Series.series_type.ilike(term)))
    if status:
        filters.append(Series.status == status)
    total = db.scalar(select(func.count(Series.id)).where(*filters)) or 0
    rows = db.scalars(
        select(Series).where(*filters)
        .options(selectinload(Series.release_links))
        .order_by(func.lower(Series.name), Series.id)
        .limit(limit).offset(offset)
    ).all()
    return {"items": [_series_payload(item) for item in rows],
            "total": total, "limit": limit, "offset": offset}


@router.get("/series/{series_id}")
def get_series(
    series_id: str,
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    series = db.scalar(
        select(Series).where(Series.id == series_id)
        .options(selectinload(Series.release_links).selectinload(ReleaseSeries.release))
    )
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found.")
    payload = _series_payload(series)
    payload["releases"] = [
        {"id": link.release.id, "name": link.release.name,
         "catalog_year": link.release.catalog_year,
         "assortment_number": link.release.assortment_number}
        for link in sorted(series.release_links,
                           key=lambda item: (item.release.catalog_year or 0,
                                             item.release.name or "", item.release.id),
                           reverse=True)
    ]
    return payload


@router.post("/series", status_code=201)
def create_series(
    body: SeriesCreate,
    request: Request,
    user: User = Depends(_require_permission("catalog.create")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    name = body.name.strip()
    reason = body.reason.strip()
    if not name or not reason:
        raise HTTPException(status_code=422, detail="Series name and creation reason are required.")
    series = Series(name=name, description=_clean_optional_text(body.description),
                    series_type=_clean_optional_text(body.series_type), status=body.status)
    try:
        db.add(series)
        db.flush()
        db.add(ChangeLog(entity_type="series", entity_id=series.id, action="create",
                         old_values=None,
                         new_values={"name": series.name, "description": series.description,
                                     "series_type": series.series_type, "status": series.status},
                         reason=reason, actor_type="user", actor_id=user.id))
        db.commit()
        db.refresh(series)
    except Exception:
        db.rollback()
        raise
    return _series_payload(series)


@router.patch("/series/{series_id}")
def patch_series(
    series_id: str,
    body: SeriesPatch,
    request: Request,
    user: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty change reason is required.")
    changes = body.model_dump(exclude_unset=True)
    changes.pop("reason", None)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one series field must be supplied.")
    if "status" in changes and changes["status"] is None:
        raise HTTPException(status_code=422, detail="Series status cannot be null.")
    if "name" in changes:
        if changes["name"] is None or not changes["name"].strip():
            raise HTTPException(status_code=422, detail="Series name cannot be empty.")
        changes["name"] = changes["name"].strip()
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found.")
    try:
        _apply_audited_patch(db, entity=series, entity_type="series",
                             changes=changes, reason=reason, user=user)
        db.commit()
        db.refresh(series)
    except Exception:
        db.rollback()
        raise
    return _series_payload(series)


@router.put("/releases/{release_id}/series")
def update_release_series(
    release_id: str,
    body: ReleaseSeriesUpdate,
    request: Request,
    user: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty change reason is required.")
    if len(set(body.series_ids)) != len(body.series_ids):
        raise HTTPException(status_code=422, detail="Duplicate series IDs are not allowed.")
    release = db.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found.")
    selected = db.scalars(select(Series).where(Series.id.in_(body.series_ids))).all() if body.series_ids else []
    if len(selected) != len(body.series_ids):
        raise HTTPException(status_code=422, detail="One or more selected series do not exist.")
    current_links = db.scalars(select(ReleaseSeries).where(ReleaseSeries.release_id == release_id)).all()
    old_ids = sorted(link.series_id for link in current_links)
    new_ids = sorted(body.series_ids)
    if old_ids == new_ids:
        return {"release_id": release_id, "series_ids": old_ids}
    try:
        for link in current_links:
            db.delete(link)
        for series_id in new_ids:
            db.add(ReleaseSeries(release_id=release_id, series_id=series_id))
        db.add(ChangeLog(entity_type="release", entity_id=release_id,
                         action="update_series", old_values={"series_ids": old_ids},
                         new_values={"series_ids": new_ids}, reason=reason,
                         actor_type="user", actor_id=user.id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"release_id": release_id, "series_ids": new_ids}


class ProductLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=240)
    description: str | None = None
    parent_product_line_id: str | None = Field(default=None, max_length=36)
    status: CastingStatus = "candidate"
    reason: str = Field(min_length=1, max_length=4000)


class ProductLinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    parent_product_line_id: str | None = Field(default=None, max_length=36)
    status: CastingStatus | None = None
    reason: str = Field(min_length=1, max_length=4000)


class ReleaseProductLinesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_line_ids: list[str] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=4000)


class ReleaseProductLineEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=1, max_length=4000)


def _normalize_product_line_name(value: str) -> tuple[str, str]:
    name = " ".join(unicodedata.normalize("NFKC", value).split())
    normalized_name = " ".join(
        unicodedata.normalize("NFKC", name.casefold()).split()
    )
    return name, normalized_name


def _normalize_product_line_code(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _product_line_payload(
    product_line: ProductLine, release_count: int = 0
) -> dict:
    return {
        "id": product_line.id,
        "code": product_line.code,
        "name": product_line.name,
        "normalized_name": product_line.normalized_name,
        "description": product_line.description,
        "parent_product_line_id": product_line.parent_product_line_id,
        "status": product_line.status,
        "release_count": release_count,
        "created_at": product_line.created_at.isoformat(),
        "updated_at": product_line.updated_at.isoformat(),
    }


def _active_release_count(product_line: ProductLine) -> int:
    return sum(
        link.membership_status == "active"
        for link in product_line.release_links
    )


def _begin_product_line_hierarchy_write(
    db: Session, lock_product_line_id: str
) -> None:
    connection = db.connection()
    if connection.dialect.name != "sqlite":
        return

    driver_connection = connection.connection.driver_connection
    if not driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        connection.execute(
            text("UPDATE product_lines SET id = id WHERE id = :product_line_id"),
            {"product_line_id": lock_product_line_id},
        )


def _validate_product_line_parent(
    db: Session,
    parent_product_line_id: str | None,
    *,
    product_line_id: str | None = None,
) -> None:
    if parent_product_line_id is None:
        return
    if parent_product_line_id == product_line_id:
        raise HTTPException(
            status_code=422,
            detail="A product line cannot be its own parent.",
        )
    if db.get(ProductLine, parent_product_line_id) is None:
        raise HTTPException(status_code=422, detail="Parent product line not found.")

    if db.get_bind().dialect.name == "sqlite":
        rows = db.execute(
            text(
                """
                WITH RECURSIVE parent_chain(id, parent_id, path, cycle) AS (
                    SELECT id, parent_product_line_id, '/' || id || '/', 0
                    FROM product_lines
                    WHERE id = :parent_id
                    UNION ALL
                    SELECT parent.id,
                           parent.parent_product_line_id,
                           parent_chain.path || parent.id || '/',
                           CASE
                               WHEN instr(parent_chain.path, '/' || parent.id || '/') > 0
                               THEN 1 ELSE 0
                           END
                    FROM product_lines AS parent
                    JOIN parent_chain ON parent.id = parent_chain.parent_id
                    WHERE parent_chain.cycle = 0
                )
                SELECT id, cycle FROM parent_chain
                """
            ),
            {"parent_id": parent_product_line_id},
        ).all()
        ancestors = {row.id for row in rows}
        if any(row.cycle for row in rows):
            raise HTTPException(
                status_code=409,
                detail="The existing product-line hierarchy contains a cycle.",
            )
    else:
        ancestors = set()
        current_id = parent_product_line_id
        while current_id is not None:
            if current_id in ancestors:
                raise HTTPException(
                    status_code=409,
                    detail="The existing product-line hierarchy contains a cycle.",
                )
            ancestors.add(current_id)
            current_id = db.scalar(
                select(ProductLine.parent_product_line_id).where(
                    ProductLine.id == current_id
                )
            )

    if product_line_id is not None and product_line_id in ancestors:
        raise HTTPException(
            status_code=422,
            detail="This parent assignment would create a product-line cycle.",
        )


def _check_product_line_unique(
    db: Session,
    *,
    code: str | None = None,
    normalized_name: str | None = None,
    exclude_id: str | None = None,
) -> None:
    conditions = []
    if code is not None:
        conditions.append(ProductLine.code == code)
    if normalized_name is not None:
        conditions.append(ProductLine.normalized_name == normalized_name)
    if not conditions:
        return

    statement = select(ProductLine.id).where(or_(*conditions))
    if exclude_id is not None:
        statement = statement.where(ProductLine.id != exclude_id)
    if db.scalar(statement.limit(1)) is not None:
        raise HTTPException(
            status_code=409,
            detail="A product line with this code or normalized name already exists.",
        )


@router.get("/product-lines")
def list_product_lines(
    q: str | None = Query(default=None, max_length=240),
    status: CastingStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    filters = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters.append(or_(ProductLine.name.ilike(term), ProductLine.code.ilike(term)))
    if status:
        filters.append(ProductLine.status == status)

    total = db.scalar(
        select(func.count(ProductLine.id)).where(*filters)
    ) or 0
    active_release_counts = (
        select(
            ReleaseProductLine.product_line_id.label("product_line_id"),
            func.count(ReleaseProductLine.id).label("release_count"),
        )
        .where(ReleaseProductLine.membership_status == "active")
        .group_by(ReleaseProductLine.product_line_id)
        .subquery()
    )
    rows = db.execute(
        select(
            ProductLine,
            func.coalesce(active_release_counts.c.release_count, 0),
        )
        .outerjoin(
            active_release_counts,
            active_release_counts.c.product_line_id == ProductLine.id,
        )
        .where(*filters)
        .order_by(func.lower(ProductLine.name), ProductLine.code, ProductLine.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [
            _product_line_payload(product_line, int(release_count))
            for product_line, release_count in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/product-lines/{product_line_id}")
def get_product_line(
    product_line_id: str,
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    product_line = db.scalar(
        select(ProductLine)
        .where(ProductLine.id == product_line_id)
        .options(
            selectinload(ProductLine.parent),
            selectinload(ProductLine.children),
            selectinload(ProductLine.release_links).selectinload(
                ReleaseProductLine.release
            ),
        )
    )
    if product_line is None:
        raise HTTPException(status_code=404, detail="Product line not found.")

    payload = _product_line_payload(
        product_line, _active_release_count(product_line)
    )
    payload["parent"] = (
        {
            "id": product_line.parent.id,
            "code": product_line.parent.code,
            "name": product_line.parent.name,
        }
        if product_line.parent is not None
        else None
    )
    payload["children"] = [
        {
            "id": child.id,
            "code": child.code,
            "name": child.name,
            "status": child.status,
        }
        for child in sorted(
            product_line.children,
            key=lambda item: (item.name.casefold(), item.id),
        )
    ]
    payload["releases"] = [
        {
            "id": link.release.id,
            "name": link.release.name,
            "catalog_year": link.release.catalog_year,
            "assortment_number": link.release.assortment_number,
            "status": link.release.status,
            "membership_status": link.membership_status,
        }
        for link in sorted(
            product_line.release_links,
            key=lambda item: (
                item.release.catalog_year or 0,
                item.release.name or "",
                item.release.id,
            ),
            reverse=True,
        )
    ]
    return payload


@router.post("/product-lines", status_code=201)
def create_product_line(
    body: ProductLineCreate,
    request: Request,
    user: User = Depends(_require_permission("catalog.create")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    name, normalized_name = _normalize_product_line_name(body.name)
    code = _normalize_product_line_code(body.code)
    if not name or not normalized_name or not code or not reason:
        raise HTTPException(
            status_code=422,
            detail="Product line name, code, and creation reason are required.",
        )
    parent_product_line_id = body.parent_product_line_id
    if parent_product_line_id is not None:
        parent_product_line_id = parent_product_line_id.strip()
        if not parent_product_line_id:
            raise HTTPException(status_code=422, detail="Parent product line ID cannot be empty.")
        _begin_product_line_hierarchy_write(db, parent_product_line_id)
    _validate_product_line_parent(db, parent_product_line_id)
    _check_product_line_unique(
        db, code=code, normalized_name=normalized_name
    )

    product_line = ProductLine(
        code=code,
        name=name,
        normalized_name=normalized_name,
        description=_clean_optional_text(body.description),
        parent_product_line_id=parent_product_line_id,
        status=body.status,
    )
    try:
        db.add(product_line)
        db.flush()
        db.add(ChangeLog(
            entity_type="product_line",
            entity_id=product_line.id,
            action="create",
            old_values=None,
            new_values={
                "code": product_line.code,
                "name": product_line.name,
                "normalized_name": product_line.normalized_name,
                "description": product_line.description,
                "parent_product_line_id": product_line.parent_product_line_id,
                "status": product_line.status,
            },
            reason=reason,
            actor_type="user",
            actor_id=user.id,
        ))
        db.commit()
        db.refresh(product_line)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Product line conflicts with an existing record or parent.",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return _product_line_payload(product_line)


@router.patch("/product-lines/{product_line_id}")
def patch_product_line(
    product_line_id: str,
    body: ProductLinePatch,
    request: Request,
    user: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty change reason is required.")

    changes = body.model_dump(exclude_unset=True)
    changes.pop("reason", None)
    if not changes:
        raise HTTPException(
            status_code=422,
            detail="At least one product-line field must be supplied.",
        )
    if "parent_product_line_id" in changes:
        _begin_product_line_hierarchy_write(db, product_line_id)
        parent_id = changes["parent_product_line_id"]
        if parent_id is not None:
            parent_id = parent_id.strip()
            if not parent_id:
                raise HTTPException(
                    status_code=422,
                    detail="Parent product line ID cannot be empty.",
                )
        changes["parent_product_line_id"] = parent_id
    if "name" in changes:
        if changes["name"] is None or not changes["name"].strip():
            raise HTTPException(status_code=422, detail="Product line name cannot be empty.")
        changes["name"], changes["normalized_name"] = _normalize_product_line_name(
            changes["name"]
        )
    if "code" in changes:
        if changes["code"] is None or not changes["code"].strip():
            raise HTTPException(status_code=422, detail="Product line code cannot be empty.")
        changes["code"] = _normalize_product_line_code(changes["code"])
    if "status" in changes and changes["status"] is None:
        raise HTTPException(status_code=422, detail="Product line status cannot be null.")
    if "description" in changes:
        changes["description"] = _clean_optional_text(changes["description"])

    product_line = db.scalar(
        select(ProductLine)
        .where(ProductLine.id == product_line_id)
        .options(selectinload(ProductLine.release_links))
    )
    if product_line is None:
        raise HTTPException(status_code=404, detail="Product line not found.")

    if "code" in changes or "normalized_name" in changes:
        _check_product_line_unique(
            db,
            code=changes.get("code"),
            normalized_name=changes.get("normalized_name"),
            exclude_id=product_line.id,
        )
    if "parent_product_line_id" in changes:
        _validate_product_line_parent(
            db,
            changes["parent_product_line_id"],
            product_line_id=product_line.id,
        )

    try:
        updated = _apply_audited_patch(
            db,
            entity=product_line,
            entity_type="product_line",
            changes=changes,
            reason=reason,
            user=user,
        )
        if not updated:
            return _product_line_payload(
                product_line, _active_release_count(product_line)
            )
        db.commit()
        db.refresh(product_line)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Product line conflicts with an existing record or parent.",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return _product_line_payload(
        product_line, _active_release_count(product_line)
    )


@router.put("/releases/{release_id}/product-lines")
def update_release_product_lines(
    release_id: str,
    body: ReleaseProductLinesUpdate,
    request: Request,
    user: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty change reason is required.")
    if len(set(body.product_line_ids)) != len(body.product_line_ids):
        raise HTTPException(status_code=422, detail="Duplicate product-line IDs are not allowed.")

    release = db.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found.")
    selected_ids = sorted(body.product_line_ids)
    selected = (
        db.scalars(
            select(ProductLine).where(ProductLine.id.in_(selected_ids))
        ).all()
        if selected_ids
        else []
    )
    if len(selected) != len(selected_ids):
        raise HTTPException(
            status_code=422,
            detail="One or more selected product lines do not exist.",
        )

    current_links = db.scalars(
        select(ReleaseProductLine)
        .where(ReleaseProductLine.release_id == release_id)
        .order_by(ReleaseProductLine.product_line_id)
    ).all()
    links_by_product_line = {
        link.product_line_id: link for link in current_links
    }
    old_active_ids = sorted(
        link.product_line_id
        for link in current_links
        if link.membership_status == "active"
    )
    selected_set = set(selected_ids)
    changed = False

    for link in current_links:
        if (
            link.membership_status == "active"
            and link.product_line_id not in selected_set
        ):
            link.membership_status = "withdrawn"
            changed = True

    for product_line_id in selected_ids:
        link = links_by_product_line.get(product_line_id)
        if link is None:
            link = ReleaseProductLine(
                release_id=release_id,
                product_line_id=product_line_id,
                membership_status="active",
            )
            db.add(link)
            current_links.append(link)
            changed = True
        elif link.membership_status == "withdrawn":
            link.membership_status = "active"
            changed = True

    if not changed:
        return {
            "release_id": release_id,
            "product_line_ids": old_active_ids,
            "assignments": [
                {
                    "id": link.id,
                    "product_line_id": link.product_line_id,
                    "membership_status": link.membership_status,
                }
                for link in current_links
            ],
        }

    try:
        db.add(ChangeLog(
            entity_type="release",
            entity_id=release_id,
            action="update_product_lines",
            old_values={"product_line_ids": old_active_ids},
            new_values={"product_line_ids": selected_ids},
            reason=reason,
            actor_type="user",
            actor_id=user.id,
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Product-line assignments conflict with current catalog data.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {
        "release_id": release_id,
        "product_line_ids": selected_ids,
        "assignments": [
            {
                "id": link.id,
                "product_line_id": link.product_line_id,
                "membership_status": link.membership_status,
            }
            for link in current_links
        ],
    }


@router.post("/release-product-lines/{release_product_line_id}/evidence", status_code=201)
def attach_evidence_to_release_product_line(
    release_product_line_id: str,
    body: ReleaseProductLineEvidenceCreate,
    request: Request,
    user: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty change reason is required.")

    assignment = db.get(ReleaseProductLine, release_product_line_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Release product-line assignment not found.")
    evidence = db.get(Evidence, body.evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found.")
    evidence_link_key = {
        "evidence_id": evidence.id,
        "release_product_line_id": assignment.id,
    }
    if db.get(EvidenceProductLine, evidence_link_key) is not None:
        raise HTTPException(
            status_code=409,
            detail="This evidence is already linked to the product-line assignment.",
        )

    evidence_link = EvidenceProductLine(
        evidence_id=evidence.id,
        release_product_line_id=assignment.id,
        role="about",
    )
    try:
        db.add(evidence_link)
        db.flush()
        db.add(ChangeLog(
            entity_type="release_product_line",
            entity_id=assignment.id,
            action="attach_evidence",
            old_values=None,
            new_values={"evidence_id": evidence.id, "role": evidence_link.role},
            reason=reason,
            actor_type="user",
            actor_id=user.id,
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Evidence could not be linked to this product-line assignment.",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return {
        "evidence_id": evidence.id,
        "release_product_line_id": assignment.id,
        "role": evidence_link.role,
    }


@router.get("/history")
def list_change_history(
    entity_type: str | None = Query(default=None, max_length=40),
    entity_id: str | None = Query(default=None, max_length=36),
    action: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    filters = []
    if entity_type:
        filters.append(ChangeLog.entity_type == entity_type)
    if entity_id:
        filters.append(ChangeLog.entity_id == entity_id)
    if action:
        filters.append(ChangeLog.action == action)
    total = db.scalar(select(func.count(ChangeLog.id)).where(*filters)) or 0
    rows = db.scalars(select(ChangeLog).where(*filters)
                      .order_by(ChangeLog.created_at.desc(), ChangeLog.id.desc())
                      .limit(limit).offset(offset)).all()
    return {
        "items": [{
            "id": item.id, "entity_type": item.entity_type, "entity_id": item.entity_id,
            "action": item.action, "old_values": item.old_values, "new_values": item.new_values,
            "reason": item.reason, "actor_type": item.actor_type, "actor_id": item.actor_id,
            "created_at": item.created_at.isoformat(),
        } for item in rows],
        "total": total, "limit": limit, "offset": offset,
    }

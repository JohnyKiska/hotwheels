"""Permission-protected catalog administration endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .account_api import _require_csrf, _require_permission
from .db import get_db
from .models import Casting, CastingVariant, ChangeLog, Release, ReleaseSeries, Series, User

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


def _release_payload(release: Release) -> dict:
    return {
        "id": release.id,
        "casting_id": release.casting_id,
        "casting_name": release.casting.name,
        "casting_variant_id": release.casting_variant_id,
        "casting_variant_name": release.casting_variant.name if release.casting_variant else None,
        "catalog_year": release.catalog_year,
        "name": release.name,
        "assortment_number": release.assortment_number,
        "description": release.description,
        "status": release.status,
        "series": [
            {"id": item.id, "name": item.name}
            for item in sorted(release.series, key=lambda item: (item.name.lower(), item.id))
        ],
        "created_at": release.created_at.isoformat(),
        "updated_at": release.updated_at.isoformat(),
    }


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
        filters.append(or_(
            Release.name.ilike(term),
            Release.assortment_number.ilike(term),
            Casting.name.ilike(term),
        ))
    if casting_id:
        filters.append(Release.casting_id == casting_id)
    if catalog_year is not None:
        filters.append(Release.catalog_year == catalog_year)
    if status:
        filters.append(Release.status == status)

    statement = select(Release).join(Casting, Casting.id == Release.casting_id).where(*filters)
    total = db.scalar(
        select(func.count(Release.id))
        .join(Casting, Casting.id == Release.casting_id)
        .where(*filters)
    ) or 0
    rows = db.scalars(
        statement.options(
            selectinload(Release.casting),
            selectinload(Release.casting_variant),
            selectinload(Release.series),
        )
        .order_by(Release.catalog_year.desc().nullslast(), Release.name, Release.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [_release_payload(item) for item in rows],
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
        )
    )
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found.")
    return _release_payload(release)


class ReleasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
        )
    )
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found.")

    if "casting_variant_id" in changes and changes["casting_variant_id"] is not None:
        from .models import CastingVariant
        variant = db.get(CastingVariant, changes["casting_variant_id"])
        if variant is None or variant.casting_id != release.casting_id:
            raise HTTPException(status_code=422, detail="Variant must belong to the release casting.")
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
    return _release_payload(release)


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

    casting_id: str = Field(min_length=1, max_length=36)
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

    casting = db.get(Casting, body.casting_id)
    if casting is None:
        raise HTTPException(status_code=404, detail="Casting not found.")
    if body.casting_variant_id is not None:
        variant = db.get(CastingVariant, body.casting_variant_id)
        if variant is None or variant.casting_id != casting.id:
            raise HTTPException(
                status_code=422,
                detail="Variant must belong to the release casting.",
            )

    release = Release(
        casting_id=casting.id,
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

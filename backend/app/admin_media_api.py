"""Permission-protected media library metadata API.

File bytes stay in external storage. This API only registers and manages metadata.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .account_api import _require_csrf, _require_permission
from .db import get_db
from .models import (
    ChangeLog, Evidence, MediaAsset, MediaAssetEvidence, Release,
    Source, SourceRecord, User,
)

router = APIRouter(prefix="/api/v1/admin/media", tags=["admin-media"])

Category = Literal["reference_photo", "evidence_photo", "package_photo", "physical_specimen", "document", "other"]
Angle = Literal["front", "rear", "left", "right", "top", "bottom", "package_front", "package_back", "detail", "other"]
AssetStatus = Literal["unreviewed", "approved", "rejected", "archived"]
RightsStatus = Literal["unknown", "permission_requested", "permitted", "restricted", "denied"]


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=240)
    source_type: str = Field(min_length=1, max_length=40)
    base_url: str | None = None
    publisher: str | None = Field(default=None, max_length=240)
    notes: str | None = None


class RecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    external_id: str | None = Field(default=None, max_length=240)
    record_url: str | None = Field(default=None, max_length=4000)
    record_type: str = Field(default="listing", min_length=1, max_length=40)
    raw_data: dict | list | None = None
    reason: str = Field(min_length=1, max_length=4000)


class AssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_record_id: str
    storage_key: str = Field(min_length=1, max_length=1000)
    original_filename: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=120)
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    description: str | None = None
    captured_at: str | None = None
    category: Category = "reference_photo"
    angle: Angle | None = None
    rights_status: RightsStatus = "unknown"
    rights_holder: str | None = Field(default=None, max_length=240)
    rights_notes: str | None = None
    contributor_name: str | None = Field(default=None, max_length=240)
    photographer_name: str | None = Field(default=None, max_length=240)
    original_media_asset_id: str | None = None
    width: int | None = Field(default=None, gt=0, le=100000)
    height: int | None = Field(default=None, gt=0, le=100000)
    byte_size: int | None = Field(default=None, ge=0, le=2_000_000_000)
    reason: str = Field(min_length=1, max_length=4000)


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category | None = None
    angle: Angle | None = None
    status: AssetStatus | None = None
    rights_status: RightsStatus | None = None
    rights_holder: str | None = Field(default=None, max_length=240)
    rights_notes: str | None = None
    contributor_name: str | None = Field(default=None, max_length=240)
    photographer_name: str | None = Field(default=None, max_length=240)
    description: str | None = None
    is_featured: bool | None = None
    reason: str = Field(min_length=1, max_length=4000)


class EvidenceLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    role: Literal["supports", "contradicts", "illustrates"] = "supports"


def _safe_storage_key(value: str) -> str:
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise HTTPException(status_code=422, detail="storage_key must be a relative POSIX path.")
    path = PurePosixPath(value)
    if any(part in ("", ".", "..") for part in path.parts):
        raise HTTPException(status_code=422, detail="storage_key contains an unsafe path segment.")
    return path.as_posix()


def _asset_payload(asset: MediaAsset) -> dict:
    record = asset.source_record
    source = record.source if record else None
    release_ids = sorted({
        link.release_id
        for evidence_link in asset.evidence_links
        for link in evidence_link.evidence.release_links
    })
    return {
        "id": asset.id, "source_record_id": asset.source_record_id,
        "source_name": source.name if source else None,
        "source_type": source.source_type if source else None,
        "record_url": record.record_url if record else None,
        "external_id": record.external_id if record else None,
        "storage_key": asset.storage_key, "original_filename": asset.original_filename,
        "mime_type": asset.mime_type, "checksum_sha256": asset.checksum_sha256,
        "description": asset.description, "captured_at": asset.captured_at.isoformat() if asset.captured_at else None,
        "category": asset.category, "angle": asset.angle, "status": asset.status,
        "rights_status": asset.rights_status, "rights_holder": asset.rights_holder,
        "rights_notes": asset.rights_notes, "contributor_name": asset.contributor_name,
        "photographer_name": asset.photographer_name, "uploader_user_id": asset.uploader_user_id,
        "original_media_asset_id": asset.original_media_asset_id,
        "width": asset.width, "height": asset.height, "byte_size": asset.byte_size,
        "is_featured": asset.is_featured, "release_ids": release_ids,
        "created_at": asset.created_at.isoformat(), "updated_at": asset.updated_at.isoformat(),
        "evidence": [{
            "id": link.evidence.id, "attribute_name": link.evidence.attribute_name,
            "observed_value": link.evidence.observed_value, "role": link.role,
        } for link in asset.evidence_links],
    }


def _audit(db: Session, actor: User, entity_id: str, action: str, old: dict, new: dict, reason: str) -> None:
    db.add(ChangeLog(
        entity_type="media_asset", entity_id=entity_id, action=action,
        old_values=old or None, new_values=new or None, reason=reason,
        actor_type="human", actor_id=actor.id,
    ))


@router.get("/sources")
def list_sources(
    _actor: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(select(Source).order_by(func.lower(Source.name), Source.id)).all()
    return {"items": [{"id": s.id, "name": s.name, "source_type": s.source_type, "base_url": s.base_url} for s in rows]}


@router.post("/sources")
def create_source(
    body: SourceCreate, request: Request,
    actor: User = Depends(_require_permission("catalog.create")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Source name cannot be empty.")
    existing = db.scalar(select(Source).where(func.lower(Source.name) == name.lower(), Source.source_type == body.source_type))
    if existing:
        return {"id": existing.id, "name": existing.name, "created": False}
    source = Source(name=name, source_type=body.source_type.strip(), base_url=body.base_url, publisher=body.publisher, notes=body.notes)
    db.add(source)
    try:
        db.flush()
        _audit(db, actor, source.id, "create", {}, {"name": name, "source_type": source.source_type}, "Media source registered")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Source already exists.")
    return {"id": source.id, "name": source.name, "created": True}


@router.get("/assets")
def list_assets(
    q: str | None = Query(default=None, max_length=240),
    source_id: str | None = None,
    category: Category | None = None,
    angle: Angle | None = None,
    status: AssetStatus | None = None,
    rights_status: RightsStatus | None = None,
    release_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _actor: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(MediaAsset).join(SourceRecord).join(Source)
    filters = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters.append(or_(MediaAsset.original_filename.ilike(term), MediaAsset.description.ilike(term), SourceRecord.external_id.ilike(term), Source.name.ilike(term)))
    if source_id: filters.append(Source.id == source_id)
    if category: filters.append(MediaAsset.category == category)
    if angle: filters.append(MediaAsset.angle == angle)
    if status: filters.append(MediaAsset.status == status)
    if rights_status: filters.append(MediaAsset.rights_status == rights_status)
    if release_id:
        stmt = stmt.join(MediaAssetEvidence).join(Evidence).join(__import__("app.models", fromlist=["EvidenceRelease"]).EvidenceRelease)
        filters.append(__import__("app.models", fromlist=["EvidenceRelease"]).EvidenceRelease.release_id == release_id)
    total = db.scalar(select(func.count(func.distinct(MediaAsset.id))).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.where(*filters).options(
        selectinload(MediaAsset.source_record).selectinload(SourceRecord.source),
        selectinload(MediaAsset.evidence_links).selectinload(MediaAssetEvidence.evidence).selectinload(Evidence.release_links),
    ).order_by(MediaAsset.created_at.desc(), MediaAsset.id).limit(limit).offset(offset).distinct()).unique().all()
    return {"items": [_asset_payload(a) for a in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/assets/{asset_id}")
def get_asset(
    asset_id: str,
    _actor: User = Depends(_require_permission("catalog.read")),
    db: Session = Depends(get_db),
) -> dict:
    asset = db.scalar(select(MediaAsset).where(MediaAsset.id == asset_id).options(
        selectinload(MediaAsset.source_record).selectinload(SourceRecord.source),
        selectinload(MediaAsset.evidence_links).selectinload(MediaAssetEvidence.evidence).selectinload(Evidence.release_links),
    ))
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found.")
    return _asset_payload(asset)


@router.post("/records")
def create_record(
    body: RecordCreate, request: Request,
    actor: User = Depends(_require_permission("catalog.create")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    if db.get(Source, body.source_id) is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    record = SourceRecord(source_id=body.source_id, external_id=body.external_id, record_url=body.record_url, record_type=body.record_type, raw_data=body.raw_data)
    db.add(record)
    try:
        db.flush()
        _audit(db, actor, record.id, "create", {}, {"source_id": record.source_id, "external_id": record.external_id, "record_url": record.record_url}, body.reason.strip())
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not register source record.")
    return {"id": record.id, "source_id": record.source_id}


@router.post("/assets")
def create_asset(
    body: AssetCreate, request: Request,
    actor: User = Depends(_require_permission("catalog.create")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty reason is required.")
    storage_key = _safe_storage_key(body.storage_key.strip())
    record = db.get(SourceRecord, body.source_record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Source record not found.")
    duplicate = db.scalar(select(MediaAsset).where(MediaAsset.checksum_sha256 == body.checksum_sha256.lower()))
    if duplicate:
        raise HTTPException(status_code=409, detail={"message": "Duplicate file checksum.", "existing_asset_id": duplicate.id})
    original = db.get(MediaAsset, body.original_media_asset_id) if body.original_media_asset_id else None
    if body.original_media_asset_id and original is None:
        raise HTTPException(status_code=404, detail="Original media asset not found.")
    from datetime import datetime
    captured_at = None
    if body.captured_at:
        try: captured_at = datetime.fromisoformat(body.captured_at.replace("Z", "+00:00"))
        except ValueError as exc: raise HTTPException(status_code=422, detail="captured_at must be ISO 8601.") from exc
    asset = MediaAsset(
        source_record_id=record.id, storage_key=storage_key, original_filename=body.original_filename,
        mime_type=body.mime_type, checksum_sha256=body.checksum_sha256.lower(), description=body.description,
        captured_at=captured_at, category=body.category, angle=body.angle, rights_status=body.rights_status,
        rights_holder=body.rights_holder, rights_notes=body.rights_notes, contributor_name=body.contributor_name,
        photographer_name=body.photographer_name, uploader_user_id=actor.id,
        original_media_asset_id=body.original_media_asset_id, width=body.width, height=body.height, byte_size=body.byte_size,
    )
    db.add(asset)
    try:
        db.flush()
        _audit(db, actor, asset.id, "create", {}, {"source_record_id": record.id, "checksum_sha256": asset.checksum_sha256, "category": asset.category, "angle": asset.angle, "rights_status": asset.rights_status}, reason)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Asset storage key or checksum conflicts with an existing record.")
    return {"id": asset.id, "created": True}


@router.patch("/assets/{asset_id}")
def patch_asset(
    asset_id: str, body: AssetPatch, request: Request,
    actor: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty reason is required.")
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found.")
    changes = body.model_dump(exclude_unset=True)
    changes.pop("reason", None)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one media field must be supplied.")
    old, new = {}, {}
    for key, value in changes.items():
        if value is not None and getattr(asset, key) != value:
            old[key], new[key] = getattr(asset, key), value
        elif value is None and key in ("angle", "rights_holder", "rights_notes", "contributor_name", "photographer_name", "description") and getattr(asset, key) is not None:
            old[key], new[key] = getattr(asset, key), None
    if not new:
        return _asset_payload(asset)
    for key, value in new.items(): setattr(asset, key, value)
    _audit(db, actor, asset.id, "update", old, new, reason)
    db.commit()
    return {"id": asset.id, "updated": True}


@router.post("/assets/{asset_id}/evidence")
def link_evidence(
    asset_id: str, body: EvidenceLinkCreate, request: Request,
    actor: User = Depends(_require_permission("catalog.update")),
    db: Session = Depends(get_db),
) -> dict:
    _require_csrf(request)
    asset, evidence = db.get(MediaAsset, asset_id), db.get(Evidence, body.evidence_id)
    if asset is None or evidence is None:
        raise HTTPException(status_code=404, detail="Media asset or evidence not found.")
    if db.get(MediaAssetEvidence, {"media_asset_id": asset.id, "evidence_id": evidence.id}):
        raise HTTPException(status_code=409, detail="Evidence is already linked to this asset.")
    db.add(MediaAssetEvidence(media_asset_id=asset.id, evidence_id=evidence.id, role=body.role))
    _audit(db, actor, asset.id, "link_evidence", {}, {"evidence_id": evidence.id, "role": body.role}, "Evidence linked to media asset")
    db.commit()
    return {"asset_id": asset.id, "evidence_id": evidence.id, "role": body.role}

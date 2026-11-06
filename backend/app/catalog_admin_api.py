"""Read-only catalog browsing endpoints for the local admin interface."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import (
    Casting,
    CatalogIdentifier,
    Evidence,
    EvidenceRelease,
    IdentifierType,
    Release,
    ReleaseIdentifier,
    ReleaseSeries,
    Series,
    Source,
    SourceRecord,
)

router = APIRouter(tags=["catalog-admin"])


def _count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


@router.get("/admin", include_in_schema=False)
def live_admin_page() -> FileResponse:
    """Serve the local, same-origin read-only catalog browser."""
    page = Path(__file__).resolve().parents[2] / "admin-live.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="Admin page not found.")
    return FileResponse(page, media_type="text/html")


@router.get("/catalog/admin/summary")
def catalog_admin_summary(session: Session = Depends(get_db)) -> dict:
    """Return real catalog totals and status distributions using SELECT only."""
    release_statuses = session.execute(
        select(Release.status, func.count()).group_by(Release.status)
    ).all()
    casting_statuses = session.execute(
        select(Casting.status, func.count()).group_by(Casting.status)
    ).all()
    evidence_statuses = session.execute(
        select(Evidence.review_status, func.count()).group_by(Evidence.review_status)
    ).all()
    years = session.scalars(
        select(Release.catalog_year)
        .where(Release.catalog_year.is_not(None))
        .distinct()
        .order_by(Release.catalog_year.desc())
    ).all()
    source_names = session.scalars(select(Source.name).order_by(Source.name)).all()

    return {
        "mode": "read_only",
        "writes_to_catalog": False,
        "totals": {
            "releases": _count(session, Release),
            "castings": _count(session, Casting),
            "series": _count(session, Series),
            "source_records": _count(session, SourceRecord),
            "evidence": _count(session, Evidence),
            "identifiers": _count(session, CatalogIdentifier),
        },
        "release_statuses": {str(key): int(value) for key, value in release_statuses},
        "casting_statuses": {str(key): int(value) for key, value in casting_statuses},
        "evidence_statuses": {str(key): int(value) for key, value in evidence_statuses},
        "catalog_years": [int(year) for year in years],
        "sources": list(source_names),
    }


@router.get("/catalog/admin/releases")
def catalog_admin_releases(
    q: str | None = Query(default=None, max_length=160),
    catalog_year: int | None = Query(default=None, ge=1968, le=2100),
    status: str | None = Query(default=None, max_length=24),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> dict:
    """Return a searchable, paginated Release list with identifiers and links."""
    filters = []
    if catalog_year is not None:
        filters.append(Release.catalog_year == catalog_year)
    if status:
        filters.append(Release.status == status.strip())

    base = select(Release, Casting).join(Casting, Casting.id == Release.casting_id)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        identifier_release_ids = (
            select(ReleaseIdentifier.release_id)
            .join(CatalogIdentifier, CatalogIdentifier.id == ReleaseIdentifier.identifier_id)
            .where(CatalogIdentifier.value.ilike(pattern))
        )
        series_release_ids = (
            select(ReleaseSeries.release_id)
            .join(Series, Series.id == ReleaseSeries.series_id)
            .where(Series.name.ilike(pattern))
        )
        filters.append(or_(
            Release.name.ilike(pattern),
            Casting.name.ilike(pattern),
            Release.id.ilike(pattern),
            Release.id.in_(identifier_release_ids),
            Release.id.in_(series_release_ids),
        ))

    if filters:
        base = base.where(*filters)

    total = int(session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0)
    rows = session.execute(
        base.order_by(Release.catalog_year.desc(), Release.name, Release.id)
        .limit(limit)
        .offset(offset)
    ).all()
    release_ids = [release.id for release, _casting in rows]

    identifiers_by_release: dict[str, list[dict]] = {rid: [] for rid in release_ids}
    if release_ids:
        identifier_rows = session.execute(
            select(
                ReleaseIdentifier.release_id,
                IdentifierType.code,
                CatalogIdentifier.value,
                ReleaseIdentifier.role,
            )
            .join(CatalogIdentifier, CatalogIdentifier.id == ReleaseIdentifier.identifier_id)
            .join(IdentifierType, IdentifierType.id == CatalogIdentifier.identifier_type_id)
            .where(ReleaseIdentifier.release_id.in_(release_ids))
            .order_by(ReleaseIdentifier.release_id, IdentifierType.code, CatalogIdentifier.value)
        ).all()
        for release_id, code, value, role in identifier_rows:
            identifiers_by_release[release_id].append({
                "type": code,
                "value": value,
                "role": role,
            })

    series_by_release: dict[str, list[str]] = {rid: [] for rid in release_ids}
    if release_ids:
        series_rows = session.execute(
            select(ReleaseSeries.release_id, Series.name)
            .join(Series, Series.id == ReleaseSeries.series_id)
            .where(ReleaseSeries.release_id.in_(release_ids))
            .order_by(ReleaseSeries.release_id, Series.name)
        ).all()
        for release_id, name in series_rows:
            series_by_release[release_id].append(name)

    evidence_counts: dict[str, int] = {rid: 0 for rid in release_ids}
    if release_ids:
        evidence_rows = session.execute(
            select(EvidenceRelease.release_id, func.count(Evidence.id))
            .join(Evidence, Evidence.id == EvidenceRelease.evidence_id)
            .where(EvidenceRelease.release_id.in_(release_ids))
            .group_by(EvidenceRelease.release_id)
        ).all()
        evidence_counts.update({rid: int(count) for rid, count in evidence_rows})

    items = []
    for release, casting in rows:
        identifiers = identifiers_by_release[release.id]
        items.append({
            "id": release.id,
            "name": release.name or casting.name,
            "catalog_year": release.catalog_year,
            "status": release.status,
            "casting_id": casting.id,
            "casting_name": casting.name,
            "assortment_number": release.assortment_number,
            "identifiers": identifiers,
            "sku": [item["value"] for item in identifiers if item["type"] == "sku"],
            "catalog_numbers": [
                item["value"] for item in identifiers if item["type"] == "catalog_number"
            ],
            "series": series_by_release[release.id],
            "evidence_count": evidence_counts[release.id],
        })

    return {
        "mode": "read_only",
        "writes_to_catalog": False,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/catalog/admin/releases/{release_id}")
def catalog_admin_release_detail(
    release_id: str,
    session: Session = Depends(get_db),
) -> dict:
    """Return a Release, its Casting, identifiers, series and source evidence."""
    row = session.execute(
        select(Release, Casting)
        .join(Casting, Casting.id == Release.casting_id)
        .where(Release.id == release_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Release not found.")

    release, casting = row
    identifiers = session.execute(
        select(IdentifierType.code, CatalogIdentifier.value, ReleaseIdentifier.role,
               ReleaseIdentifier.source_note)
        .join(CatalogIdentifier, CatalogIdentifier.id == ReleaseIdentifier.identifier_id)
        .join(IdentifierType, IdentifierType.id == CatalogIdentifier.identifier_type_id)
        .where(ReleaseIdentifier.release_id == release_id)
        .order_by(IdentifierType.code, CatalogIdentifier.value)
    ).all()
    series = session.scalars(
        select(Series.name)
        .join(ReleaseSeries, ReleaseSeries.series_id == Series.id)
        .where(ReleaseSeries.release_id == release_id)
        .order_by(Series.name)
    ).all()
    evidence_rows = session.execute(
        select(Evidence, SourceRecord, Source)
        .join(EvidenceRelease, EvidenceRelease.evidence_id == Evidence.id)
        .join(SourceRecord, SourceRecord.id == Evidence.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(EvidenceRelease.release_id == release_id)
        .order_by(Evidence.attribute_name, Evidence.id)
    ).all()

    return {
        "mode": "read_only",
        "writes_to_catalog": False,
        "release": {
            "id": release.id,
            "name": release.name,
            "catalog_year": release.catalog_year,
            "assortment_number": release.assortment_number,
            "description": release.description,
            "status": release.status,
            "created_at": release.created_at.isoformat() if release.created_at else None,
        },
        "casting": {
            "id": casting.id,
            "name": casting.name,
            "status": casting.status,
            "first_known_year": casting.first_known_year,
        },
        "identifiers": [
            {"type": code, "value": value, "role": role, "source_note": note}
            for code, value, role, note in identifiers
        ],
        "series": list(series),
        "evidence": [
            {
                "id": evidence.id,
                "attribute": evidence.attribute_name,
                "value": evidence.observed_value,
                "assessment": evidence.assessment,
                "review_status": evidence.review_status,
                "notes": evidence.notes,
                "source": source.name,
                "source_record_id": source_record.id,
                "source_record_type": source_record.record_type,
                "source_url": source_record.record_url,
                "external_id": source_record.external_id,
                "raw_data": source_record.raw_data,
            }
            for evidence, source_record, source in evidence_rows
        ],
    }

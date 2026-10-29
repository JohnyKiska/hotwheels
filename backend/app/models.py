"""Core SQLAlchemy models for the Hot Wheels test catalog.

Identity decisions and source evidence are deliberately kept separate from these
core records; those supporting models will be added in later steps.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    JSON,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    """Return a stable, opaque internal ID independent of catalog numbers."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Casting(TimestampMixin, Base):
    """Base casting identity, independent of a particular year's release."""

    __tablename__ = "castings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    first_known_year: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'under_review', 'confirmed', 'rejected')",
            name="ck_castings_status",
        ),
        CheckConstraint(
            "first_known_year IS NULL OR first_known_year BETWEEN 1968 AND 2100",
            name="ck_castings_first_known_year",
        ),
    )

    variants: Mapped[list[CastingVariant]] = relationship(
        back_populates="casting", cascade="all, delete-orphan"
    )
    releases: Mapped[list[Release]] = relationship(back_populates="casting")


class CastingVariant(TimestampMixin, Base):
    """A supported construction variant within a casting."""

    __tablename__ = "casting_variants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    casting_id: Mapped[str] = mapped_column(
        ForeignKey("castings.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'under_review', 'confirmed', 'rejected')",
            name="ck_casting_variants_status",
        ),
        # Required as the target of Release's composite foreign key.
        UniqueConstraint("id", "casting_id", name="uq_variant_id_casting"),
    )

    casting: Mapped[Casting] = relationship(back_populates="variants")
    releases: Mapped[list[Release]] = relationship(
        back_populates="casting_variant",
        foreign_keys="Release.casting_variant_id",
        # Let the database RESTRICT constraint protect referenced variants.
        passive_deletes="all",
    )


class Series(TimestampMixin, Base):
    """A named series; catalog navigation/grouping is modelled separately."""

    __tablename__ = "series"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    series_type: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'under_review', 'confirmed', 'rejected')",
            name="ck_series_status",
        ),
    )

    release_links: Mapped[list[ReleaseSeries]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )
    releases: Mapped[list[Release]] = relationship(
        secondary="release_series", back_populates="series", viewonly=True
    )


class ReleaseSeries(Base):
    """Many-to-many link: a release can belong to multiple series."""

    __tablename__ = "release_series"

    release_id: Mapped[str] = mapped_column(
        ForeignKey("releases.id", ondelete="RESTRICT"), primary_key=True
    )
    series_id: Mapped[str] = mapped_column(
        ForeignKey("series.id", ondelete="RESTRICT"), primary_key=True
    )
    relation_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    release: Mapped[Release] = relationship(back_populates="series_links")
    series: Mapped[Series] = relationship(back_populates="release_links")


class Release(TimestampMixin, Base):
    """A distinct catalog-year release of a casting."""

    __tablename__ = "releases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    casting_id: Mapped[str] = mapped_column(
        ForeignKey("castings.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Nullable until the particular construction variant has enough evidence.
    casting_variant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    catalog_year: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str | None] = mapped_column(String(240))
    assortment_number: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'under_review', 'confirmed', 'rejected')",
            name="ck_releases_status",
        ),
        CheckConstraint(
            "catalog_year IS NULL OR catalog_year BETWEEN 1968 AND 2100",
            name="ck_releases_catalog_year",
        ),
        UniqueConstraint(
            "casting_id", "catalog_year", "assortment_number",
            name="uq_release_casting_year_assortment",
        ),
        # SQLite checks that a selected variant belongs to this exact casting.
        ForeignKeyConstraint(
            ["casting_variant_id", "casting_id"],
            ["casting_variants.id", "casting_variants.casting_id"],
            name="fk_release_variant_same_casting",
            ondelete="RESTRICT",
        ),
    )

    casting: Mapped[Casting] = relationship(back_populates="releases", foreign_keys=[casting_id])
    casting_variant: Mapped[CastingVariant | None] = relationship(
        back_populates="releases", foreign_keys=[casting_variant_id]
    )
    series_links: Mapped[list[ReleaseSeries]] = relationship(
        back_populates="release", cascade="all, delete-orphan"
    )
    series: Mapped[list[Series]] = relationship(
        secondary="release_series", back_populates="releases", viewonly=True
    )


class Source(TimestampMixin, Base):
    """A source system, website, catalog, file collection, or physical reference."""
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(240))
    is_official: Mapped[bool] = mapped_column(default=False, nullable=False)
    access_method: Mapped[str | None] = mapped_column(String(40))
    access_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("access_status IN ('unknown', 'available', 'restricted', 'blocked', 'retired')",
                        name="ck_sources_access_status"),
    )
    records: Mapped[list[SourceRecord]] = relationship(
        back_populates="source",
        # Source records are historical snapshots; deleting a source must not erase them.
        passive_deletes="all",
    )


class SourceRecord(TimestampMixin, Base):
    """A captured source record. New observations should create new records/snapshots."""
    __tablename__ = "source_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(240), index=True)
    record_url: Mapped[str | None] = mapped_column(Text)
    record_type: Mapped[str] = mapped_column(String(40), nullable=False)
    raw_data: Mapped[dict | list | None] = mapped_column(JSON)
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'superseded', 'unavailable', 'rejected')",
                        name="ck_source_records_status"),
    )
    source: Mapped[Source] = relationship(back_populates="records")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="source_record",
        # Evidence is an audit trail and must not disappear with a source snapshot.
        passive_deletes="all",
    )
    media_assets: Mapped[list[MediaAsset]] = relationship(
        back_populates="source_record",
        passive_deletes="all",
    )


class Evidence(TimestampMixin, Base):
    """One observed claim; entity links are separate so a claim can support several records."""
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_record_id: Mapped[str] = mapped_column(ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False, index=True)
    attribute_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    observed_value: Mapped[str | None] = mapped_column(Text)
    evidence_type: Mapped[str] = mapped_column(String(40), default="text", nullable=False)
    assessment: Mapped[str] = mapped_column(String(24), default="supports", nullable=False)
    review_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("assessment IN ('supports', 'contradicts', 'inconclusive')", name="ck_evidence_assessment"),
        CheckConstraint("review_status IN ('pending', 'auto_reviewed', 'manually_verified', 'rejected')",
                        name="ck_evidence_review_status"),
    )
    source_record: Mapped[SourceRecord] = relationship(back_populates="evidence")
    casting_links: Mapped[list[EvidenceCasting]] = relationship(back_populates="evidence", cascade="all, delete-orphan")
    variant_links: Mapped[list[EvidenceCastingVariant]] = relationship(back_populates="evidence", cascade="all, delete-orphan")
    release_links: Mapped[list[EvidenceRelease]] = relationship(back_populates="evidence", cascade="all, delete-orphan")
    series_links: Mapped[list[EvidenceSeries]] = relationship(back_populates="evidence", cascade="all, delete-orphan")
    package_links: Mapped[list[EvidencePackage]] = relationship(back_populates="evidence", cascade="all, delete-orphan")


class MediaAsset(TimestampMixin, Base):
    """Media bytes live in file/object storage; the database stores metadata and a storage key."""
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_record_id: Mapped[str] = mapped_column(ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_record: Mapped[SourceRecord] = relationship(back_populates="media_assets")


class EvidenceCasting(Base):
    __tablename__ = "evidence_castings"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)
    casting_id: Mapped[str] = mapped_column(ForeignKey("castings.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="about", nullable=False)
    evidence: Mapped[Evidence] = relationship(back_populates="casting_links")
    casting: Mapped[Casting] = relationship()


class EvidenceCastingVariant(Base):
    __tablename__ = "evidence_casting_variants"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)
    casting_variant_id: Mapped[str] = mapped_column(ForeignKey("casting_variants.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="about", nullable=False)
    evidence: Mapped[Evidence] = relationship(back_populates="variant_links")
    casting_variant: Mapped[CastingVariant] = relationship()


class EvidenceRelease(Base):
    __tablename__ = "evidence_releases"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)
    release_id: Mapped[str] = mapped_column(ForeignKey("releases.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="about", nullable=False)
    evidence: Mapped[Evidence] = relationship(back_populates="release_links")
    release: Mapped[Release] = relationship()


class EvidenceSeries(Base):
    __tablename__ = "evidence_series"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)
    series_id: Mapped[str] = mapped_column(ForeignKey("series.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="about", nullable=False)
    evidence: Mapped[Evidence] = relationship(back_populates="series_links")
    series: Mapped[Series] = relationship()


class Conflict(TimestampMixin, Base):
    __tablename__ = "conflicts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conflict_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)
    severity: Mapped[str] = mapped_column(String(24), default="medium", nullable=False)
    attribute_name: Mapped[str | None] = mapped_column(String(120))
    resolution: Mapped[str | None] = mapped_column(Text)
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('open', 'under_review', 'resolved', 'accepted_difference')", name="ck_conflicts_status"),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_conflicts_severity"),
    )
    evidence_links: Mapped[list[ConflictEvidence]] = relationship(back_populates="conflict", cascade="all, delete-orphan")


class ConflictEvidence(Base):
    __tablename__ = "conflict_evidence"
    conflict_id: Mapped[str] = mapped_column(ForeignKey("conflicts.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="context", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    conflict: Mapped[Conflict] = relationship(back_populates="evidence_links")
    evidence: Mapped[Evidence] = relationship()


class ChangeLog(Base):
    """Append-only by application convention; entity_id is polymorphic and validated by services."""
    __tablename__ = "change_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    old_values: Mapped[dict | list | None] = mapped_column(JSON)
    new_values: Mapped[dict | list | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(24), default="system", nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    evidence_links: Mapped[list[ChangeLogEvidence]] = relationship(back_populates="change_log", cascade="all, delete-orphan")


class ChangeLogEvidence(Base):
    __tablename__ = "change_log_evidence"
    change_log_id: Mapped[str] = mapped_column(ForeignKey("change_log.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="justification", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    change_log: Mapped[ChangeLog] = relationship(back_populates="evidence_links")
    evidence: Mapped[Evidence] = relationship()


class IdentifierType(TimestampMixin, Base):
    """A namespace for catalog identifiers; values are not globally unique by default."""
    __tablename__ = "identifier_types"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    normalization_rule: Mapped[str | None] = mapped_column(String(80))
    is_globally_unique: Mapped[bool] = mapped_column(default=False, nullable=False)


class CatalogIdentifier(TimestampMixin, Base):
    """Canonical identifier value, separated from observations and entity assignments."""
    __tablename__ = "catalog_identifiers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identifier_type_id: Mapped[str] = mapped_column(
        ForeignKey("identifier_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    normalized_value: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("identifier_type_id", "normalized_value", name="uq_identifier_type_normalized_value"),
    )
    identifier_type: Mapped[IdentifierType] = relationship()


class ReleaseIdentifier(Base):
    __tablename__ = "release_identifiers"
    release_id: Mapped[str] = mapped_column(ForeignKey("releases.id", ondelete="RESTRICT"), primary_key=True)
    identifier_id: Mapped[str] = mapped_column(ForeignKey("catalog_identifiers.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="primary", nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text)
    release: Mapped[Release] = relationship()
    identifier: Mapped[CatalogIdentifier] = relationship()


class CastingIdentifier(Base):
    __tablename__ = "casting_identifiers"
    casting_id: Mapped[str] = mapped_column(ForeignKey("castings.id", ondelete="RESTRICT"), primary_key=True)
    identifier_id: Mapped[str] = mapped_column(ForeignKey("catalog_identifiers.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="primary", nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text)
    casting: Mapped[Casting] = relationship()
    identifier: Mapped[CatalogIdentifier] = relationship()


class CastingVariantIdentifier(Base):
    __tablename__ = "casting_variant_identifiers"
    casting_variant_id: Mapped[str] = mapped_column(ForeignKey("casting_variants.id", ondelete="RESTRICT"), primary_key=True)
    identifier_id: Mapped[str] = mapped_column(ForeignKey("catalog_identifiers.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="primary", nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text)
    casting_variant: Mapped[CastingVariant] = relationship()
    identifier: Mapped[CatalogIdentifier] = relationship()



class Package(TimestampMixin, Base):
    """A sellable package or multipack, distinct from the individual releases inside it."""

    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str | None] = mapped_column(String(240), index=True)
    package_type: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    catalog_year: Mapped[int | None] = mapped_column(Integer, index=True)
    declared_quantity: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'under_review', 'confirmed', 'rejected')",
            name="ck_packages_status",
        ),
        CheckConstraint(
            "catalog_year IS NULL OR catalog_year BETWEEN 1968 AND 2100",
            name="ck_packages_catalog_year",
        ),
        CheckConstraint(
            "declared_quantity IS NULL OR declared_quantity >= 1",
            name="ck_packages_declared_quantity",
        ),
    )

    release_links: Mapped[list[PackageRelease]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )
    identifier_links: Mapped[list[PackageIdentifier]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )
    evidence_links: Mapped[list[EvidencePackage]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )


class PackageRelease(Base):
    """Ordered composition entry; one release may appear more than once in a package."""

    __tablename__ = "package_releases"

    package_id: Mapped[str] = mapped_column(
        ForeignKey("packages.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("releases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("package_id", "position", name="uq_package_release_position"),
        CheckConstraint("position >= 1", name="ck_package_release_position"),
        CheckConstraint("quantity >= 1", name="ck_package_release_quantity"),
    )

    package: Mapped[Package] = relationship(back_populates="release_links")
    release: Mapped[Release] = relationship()


class PackageIdentifier(Base):
    """Assign a typed catalog identifier to a package without reusing a car's identifier."""

    __tablename__ = "package_identifiers"

    package_id: Mapped[str] = mapped_column(
        ForeignKey("packages.id", ondelete="CASCADE"), primary_key=True
    )
    identifier_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_identifiers.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), default="primary", nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text)

    package: Mapped[Package] = relationship(back_populates="identifier_links")
    identifier: Mapped[CatalogIdentifier] = relationship()


class EvidencePackage(Base):
    """Link source evidence to a package independently of the releases it contains."""

    __tablename__ = "evidence_packages"

    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True
    )
    package_id: Mapped[str] = mapped_column(
        ForeignKey("packages.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), default="about", nullable=False)

    evidence: Mapped[Evidence] = relationship(back_populates="package_links")
    package: Mapped[Package] = relationship(back_populates="evidence_links")

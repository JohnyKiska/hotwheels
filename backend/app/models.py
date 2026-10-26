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

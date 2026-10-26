from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class Casting(TimestampMixin, Base):
    __tablename__ = "castings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(250), nullable=False, index=True)
    first_known_year: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)
    releases: Mapped[list["Release"]] = relationship(back_populates="casting")
    variants: Mapped[list["CastingVariant"]] = relationship(back_populates="casting")
    __table_args__ = (CheckConstraint("status IN ('candidate','under_review','confirmed','rejected')", name="ck_casting_status"),)


class CastingVariant(TimestampMixin, Base):
    __tablename__ = "casting_variants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    casting_id: Mapped[str] = mapped_column(ForeignKey("castings.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(250))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)
    casting: Mapped["Casting"] = relationship(back_populates="variants")
    releases: Mapped[list["Release"]] = relationship(back_populates="variant")
    __table_args__ = (CheckConstraint("status IN ('candidate','under_review','confirmed','rejected')", name="ck_variant_status"),)


class Release(TimestampMixin, Base):
    __tablename__ = "releases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    casting_id: Mapped[str] = mapped_column(ForeignKey("castings.id", ondelete="RESTRICT"), nullable=False, index=True)
    variant_id: Mapped[str | None] = mapped_column(ForeignKey("casting_variants.id", ondelete="RESTRICT"), index=True)
    catalog_year: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str | None] = mapped_column(String(250))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)
    casting: Mapped["Casting"] = relationship(back_populates="releases")
    variant: Mapped["CastingVariant | None"] = relationship(back_populates="releases")
    identifiers: Mapped[list["ProductIdentifier"]] = relationship(back_populates="release")
    __table_args__ = (
        CheckConstraint("status IN ('candidate','under_review','confirmed','rejected')", name="ck_release_status"),
        CheckConstraint("catalog_year IS NULL OR (catalog_year >= 1968 AND catalog_year <= 2200)", name="ck_release_year"),
    )


class Series(TimestampMixin, Base):
    __tablename__ = "series"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(250), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)
    release_links: Mapped[list["ReleaseSeries"]] = relationship(back_populates="series")
    __table_args__ = (CheckConstraint("status IN ('candidate','under_review','confirmed','rejected')", name="ck_series_status"),)


class ReleaseSeries(Base):
    __tablename__ = "release_series"
    release_id: Mapped[str] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True)
    series_id: Mapped[str] = mapped_column(ForeignKey("series.id", ondelete="RESTRICT"), primary_key=True)
    series: Mapped["Series"] = relationship(back_populates="release_links")


class Source(TimestampMixin, Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(250), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="website")
    base_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SourceAssertion(Base):
    __tablename__ = "source_assertions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    raw_value: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    field_status: Mapped[str] = mapped_column(String(24), nullable=False, default="observed")
    source_url: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        CheckConstraint("field_status IN ('observed','not_provided','not_found','parse_error','ambiguous','not_applicable')", name="ck_assertion_field_status"),
        Index("ix_assertion_target_field", "target_type", "target_id", "field_name"),
    )


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    evidence_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str | None] = mapped_column(String(250))
    uri: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class AssertionEvidence(Base):
    __tablename__ = "assertion_evidence"
    assertion_id: Mapped[str] = mapped_column(ForeignKey("source_assertions.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True)
    supports: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rationale: Mapped[str | None] = mapped_column(Text)


class ProductIdentifier(TimestampMixin, Base):
    __tablename__ = "product_identifiers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    release_id: Mapped[str | None] = mapped_column(ForeignKey("releases.id", ondelete="RESTRICT"), index=True)
    identifier_type: Mapped[str] = mapped_column(String(40), nullable=False)
    raw_value: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(String(160), index=True)
    verification_status: Mapped[str] = mapped_column(String(24), default="provisional", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    release: Mapped["Release | None"] = relationship(back_populates="identifiers")
    __table_args__ = (CheckConstraint("verification_status IN ('confirmed','provisional','contradictory','unknown')", name="ck_identifier_status"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False, default="system")
    actor_id: Mapped[str | None] = mapped_column(String(36))
    actor_name_snapshot: Mapped[str | None] = mapped_column(String(250))
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)

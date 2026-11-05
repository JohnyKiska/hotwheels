"""Persistent, append-only records for Casting grouping review sessions.

These tables store review workflow state only. They never mutate catalog entities.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _new_review_id() -> str:
    return str(uuid.uuid4())


def _review_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CastingGroupingReviewSession(Base):
    __tablename__ = "casting_grouping_review_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_review_id)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_review_utc_now
    )
    product_line: Mapped[str] = mapped_column(String(120), nullable=False)
    catalog_year: Mapped[int | None] = mapped_column(Integer)
    contract: Mapped[str] = mapped_column(String(120), nullable=False)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    grouping_key: Mapped[list] = mapped_column(JSON, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog_input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "catalog_year IS NULL OR catalog_year BETWEEN 1968 AND 2100",
            name="ck_casting_review_session_year",
        ),
        CheckConstraint("contract_version >= 1", name="ck_casting_review_session_contract_version"),
    )


class CastingGroupingReviewDecision(Base):
    __tablename__ = "casting_grouping_review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_review_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("casting_grouping_review_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    proposal_id: Mapped[str] = mapped_column(String(160), nullable=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_label: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    previous_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("casting_grouping_review_decisions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_review_utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "disposition IN ('accepted', 'rejected', 'needs_more_evidence')",
            name="ck_casting_grouping_review_disposition",
        ),
        Index(
            "ix_casting_grouping_review_decisions_session_proposal",
            "session_id",
            "proposal_id",
        ),
    )

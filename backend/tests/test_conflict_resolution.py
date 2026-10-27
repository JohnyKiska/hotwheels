from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.conflict_resolution import (
    InvalidConflictResolution,
    UnknownConflict,
    resolve_conflict,
)
from app.db import Base
from app.evidence_conflicts import detect_evidence_disagreements
from app.models import (
    ChangeLog,
    ChangeLogEvidence,
    Conflict,
    ConflictEvidence,
    Evidence,
    EvidenceRelease,
    Release,
    Source,
    SourceRecord,
)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_conflict(session):
    release = Release(casting_id="casting-id", catalog_year=2026, name="Example")
    # A Release requires a real Casting FK, so create the parent first.
    from app.models import Casting
    casting = Casting(id="casting-id", name="Example casting", status="confirmed")
    session.add(casting)
    session.flush()
    session.add(release)
    source = Source(name="Catalog source", source_type="website", access_status="available")
    session.add(source)
    session.flush()
    records = [
        SourceRecord(source_id=source.id, record_type="catalog_entry"),
        SourceRecord(source_id=source.id, record_type="catalog_entry"),
    ]
    session.add_all(records)
    session.flush()
    evidence_rows = [
        Evidence(source_record_id=records[0].id, attribute_name="wheel_type",
                 observed_value="PR5", evidence_type="text", assessment="supports"),
        Evidence(source_record_id=records[1].id, attribute_name="wheel_type",
                 observed_value="OH5", evidence_type="text", assessment="supports"),
    ]
    session.add_all(evidence_rows)
    session.flush()
    session.add_all([
        EvidenceRelease(evidence_id=e.id, release_id=release.id)
        for e in evidence_rows
    ])
    session.flush()
    conflict = detect_evidence_disagreements(
        session, entity_type="release", entity_id=release.id
    )[0]
    return conflict, evidence_rows, release


def test_resolve_conflict_records_decision_and_cited_evidence_without_mutating_claims():
    with make_session() as session:
        conflict, evidence_rows, release = seed_conflict(session)
        result = resolve_conflict(
            session,
            conflict_id=conflict.id,
            status="resolved",
            resolution="Use PR5 for this release",
            reason="Official catalog photo and base marking agree",
            actor_type="human",
            actor_id="reviewer-1",
            evidence_ids=[evidence_rows[0].id],
        )

        assert result.status == "resolved"
        assert result.resolution == "Use PR5 for this release"
        assert result.resolution_reason == "Official catalog photo and base marking agree"
        assert result.resolved_at is not None
        assert release.status == "candidate"
        assert [e.review_status for e in evidence_rows] == ["pending", "pending"]
        change = session.scalar(
            select(ChangeLog).where(ChangeLog.entity_id == conflict.id)
        )
        assert change.action == "resolve_conflict"
        assert change.actor_type == "human"
        assert change.actor_id == "reviewer-1"
        assert change.old_values["status"] == "open"
        assert change.new_values["status"] == "resolved"
        links = session.scalars(
            select(ChangeLogEvidence).where(ChangeLogEvidence.change_log_id == change.id)
        ).all()
        assert [link.evidence_id for link in links] == [evidence_rows[0].id]


def test_accepting_difference_is_a_final_status_and_can_be_recorded():
    with make_session() as session:
        conflict, _, _ = seed_conflict(session)
        result = resolve_conflict(
            session,
            conflict_id=conflict.id,
            status="accepted_difference",
            resolution="Both wheel types are valid market variants",
            reason="Packaging and year evidence show separate variants",
        )
        assert result.status == "accepted_difference"
        assert session.scalar(select(func.count()).select_from(ChangeLog)) == 1


def test_resolution_requires_reason_and_resolution():
    with make_session() as session:
        conflict, _, _ = seed_conflict(session)
        for kwargs in (
            {"resolution": "A decision", "reason": "   "},
            {"resolution": "", "reason": "Reason"},
        ):
            try:
                resolve_conflict(
                    session, conflict_id=conflict.id, status="resolved", **kwargs
                )
            except InvalidConflictResolution:
                pass
            else:
                raise AssertionError("blank resolution details must be rejected")
        assert conflict.status == "open"
        assert session.scalar(select(func.count()).select_from(ChangeLog)) == 0


def test_cited_evidence_must_already_belong_to_conflict():
    with make_session() as session:
        conflict, evidence_rows, _ = seed_conflict(session)
        outsider = Evidence(
            source_record_id=evidence_rows[0].source_record_id,
            attribute_name="color",
            observed_value="red",
            evidence_type="text",
            assessment="supports",
        )
        session.add(outsider)
        session.flush()
        try:
            resolve_conflict(
                session, conflict_id=conflict.id, status="resolved",
                resolution="Decision", reason="Reason", evidence_ids=[outsider.id],
            )
        except InvalidConflictResolution as exc:
            assert "linked to this conflict" in str(exc)
        else:
            raise AssertionError("unlinked evidence must not be accepted as justification")
        assert conflict.status == "open"


def test_final_conflict_cannot_be_resolved_again_and_unknown_id_is_rejected():
    with make_session() as session:
        conflict, _, _ = seed_conflict(session)
        resolve_conflict(
            session, conflict_id=conflict.id, status="resolved",
            resolution="Decision", reason="Reason",
        )
        try:
            resolve_conflict(
                session, conflict_id=conflict.id, status="accepted_difference",
                resolution="Overwrite", reason="Second decision",
            )
        except InvalidConflictResolution as exc:
            assert "already final" in str(exc)
        else:
            raise AssertionError("final conflict must not be overwritten")

        try:
            resolve_conflict(
                session, conflict_id="missing", status="resolved",
                resolution="Decision", reason="Reason",
            )
        except UnknownConflict:
            pass
        else:
            raise AssertionError("unknown conflict must be rejected")

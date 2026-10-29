from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app.db import Base, get_db
from app.main import app
from app.models import ChangeLog, Conflict


def test_resolution_endpoint_commits_auditable_decision():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        conflict = Conflict(
            conflict_type="evidence_disagreement",
            status="open",
            severity="medium",
            attribute_name="wheel_type",
        )
        session.add(conflict)
        session.commit()
        conflict_id = conflict.id

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            f"/conflicts/{conflict_id}/resolve",
            json={
                "status": "resolved",
                "resolution": "Keep PR5 as the supported value",
                "reason": "Compared the source observations",
                "actor_type": "human",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"

    with Session(engine) as session:
        saved_conflict = session.get(Conflict, conflict_id)
        assert saved_conflict.status == "resolved"
        assert saved_conflict.resolution == "Keep PR5 as the supported value"
        assert saved_conflict.resolution_reason == "Compared the source observations"
        audit_entries = session.query(ChangeLog).filter_by(
            entity_type="conflict",
            entity_id=conflict_id,
            action="resolve_conflict",
        ).all()
        assert len(audit_entries) == 1
        assert audit_entries[0].reason == "Compared the source observations"


def test_resolution_endpoint_returns_404_for_unknown_conflict():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/conflicts/missing/resolve",
            json={
                "status": "resolved",
                "resolution": "No decision",
                "reason": "Test missing conflict",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404



def test_resolution_endpoint_returns_422_for_blank_reason():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        conflict = Conflict(
            conflict_type="evidence_disagreement",
            status="open",
            severity="medium",
            attribute_name="wheel_type",
        )
        session.add(conflict)
        session.commit()
        conflict_id = conflict.id

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            f"/conflicts/{conflict_id}/resolve",
            json={
                "status": "resolved",
                "resolution": "Keep the supported value",
                "reason": "   ",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422
    with Session(engine) as session:
        saved_conflict = session.get(Conflict, conflict_id)
        assert saved_conflict.status == "open"
        assert session.query(ChangeLog).count() == 0


def test_resolution_endpoint_rejects_unknown_final_status():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        conflict = Conflict(
            conflict_type="evidence_disagreement",
            status="open",
            severity="medium",
            attribute_name="wheel_type",
        )
        session.add(conflict)
        session.commit()
        conflict_id = conflict.id

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            f"/conflicts/{conflict_id}/resolve",
            json={
                "status": "closed",
                "resolution": "Keep the supported value",
                "reason": "Compared source observations",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422
    with Session(engine) as session:
        saved_conflict = session.get(Conflict, conflict_id)
        assert saved_conflict.status == "open"
        assert session.query(ChangeLog).count() == 0


def test_revision_endpoint_appends_audit_event_and_returns_current_decision():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        conflict = Conflict(
            conflict_type="evidence_disagreement",
            status="resolved",
            severity="medium",
            attribute_name="wheel_type",
            resolution="Use PR5",
            resolution_reason="First source comparison",
        )
        session.add(conflict)
        session.commit()
        conflict_id = conflict.id
        # Seed the original decision event as it would exist after normal resolution.
        session.add(ChangeLog(
            entity_type="conflict",
            entity_id=conflict_id,
            action="resolve_conflict",
            old_values={"status": "open", "resolution": None},
            new_values={"status": "resolved", "resolution": "Use PR5"},
            reason="First source comparison",
            actor_type="human",
            actor_id="reviewer-1",
        ))
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            f"/conflicts/{conflict_id}/revise-resolution",
            json={
                "status": "accepted_difference",
                "resolution": "Both wheel types are valid variants",
                "reason": "Physical package photos support two releases",
                "actor_type": "human",
                "actor_id": "reviewer-2",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json()["status"] == "accepted_difference"
    assert response.json()["resolution"] == "Both wheel types are valid variants"
    with Session(engine) as session:
        saved_conflict = session.get(Conflict, conflict_id)
        assert saved_conflict.status == "accepted_difference"
        entries = session.query(ChangeLog).filter_by(
            entity_type="conflict", entity_id=conflict_id
        ).order_by(ChangeLog.created_at.asc(), ChangeLog.id.asc()).all()
        assert [entry.action for entry in entries] == [
            "resolve_conflict", "revise_conflict_resolution"
        ]
        assert entries[0].new_values["resolution"] == "Use PR5"
        assert entries[1].old_values["resolution"] == "Use PR5"
        assert entries[1].new_values["resolution"] == "Both wheel types are valid variants"


def test_revision_endpoint_rejects_open_conflict_and_blank_reason():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        conflict = Conflict(
            conflict_type="evidence_disagreement",
            status="open",
            severity="medium",
            attribute_name="wheel_type",
        )
        session.add(conflict)
        session.commit()
        conflict_id = conflict.id

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        open_response = client.post(
            f"/conflicts/{conflict_id}/revise-resolution",
            json={
                "status": "resolved",
                "resolution": "Decision",
                "reason": "Not a revision",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert open_response.status_code == 422
    with Session(engine) as session:
        assert session.get(Conflict, conflict_id).status == "open"
        assert session.query(ChangeLog).count() == 0


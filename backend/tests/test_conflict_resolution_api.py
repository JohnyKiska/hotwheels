from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base, get_db
from app.main import app
from app.models import Conflict


def test_resolution_endpoint_commits_auditable_decision():
    engine = create_engine("sqlite:///:memory:")
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


def test_resolution_endpoint_returns_404_for_unknown_conflict():
    engine = create_engine("sqlite:///:memory:")
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

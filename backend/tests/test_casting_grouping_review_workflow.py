from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.casting_grouping_api import _build_reviewed_remediation_plan

from pathlib import Path
import re


def test_admin_review_translations_cover_all_action_and_decision_codes():
    admin_html = Path(__file__).resolve().parents[2].joinpath("admin-live.html").read_text(
        encoding="utf-8"
    )

    locale_match = re.search(
        r"const text=\{\s*ru:\{(.*?)\},\s*en:\{(.*?)\}\s*\};",
        admin_html,
        re.DOTALL,
    )
    assert locale_match, "Review UI must define Russian and English dictionaries"
    locale_keys = []
    for locale_body in locale_match.groups():
        keys = set(re.findall(r"(?:^|,)\s*([a-zA-Z][a-zA-Z0-9]*):", locale_body))
        assert keys, "Translation dictionary must not be empty"
        locale_keys.append(keys)
    assert locale_keys[0] == locale_keys[1], (
        f"Missing locale keys: ru-only={locale_keys[0] - locale_keys[1]}, "
        f"en-only={locale_keys[1] - locale_keys[0]}"
    )

    action_match = re.search(r"const actionLabels=\{(.*?)\};", admin_html, re.DOTALL)
    assert action_match, "Review UI must define action labels"
    action_entries = re.findall(
        r"([a-z][a-z0-9_]+):\{ru:\"([^\"]+)\",en:\"([^\"]+)\"\}",
        action_match.group(1),
    )
    action_labels = {code: (ru, en) for code, ru, en in action_entries}
    expected_actions = {
        "keep_existing_link_candidate",
        "split_candidate_manual_review",
        "merge_candidate_manual_review",
        "new_casting_candidate",
        "manual_review",
    }
    assert set(action_labels) == expected_actions, (
        f"Action translation coverage mismatch: missing={expected_actions - set(action_labels)}, "
        f"unexpected={set(action_labels) - expected_actions}"
    )
    assert all(ru.strip() and en.strip() for ru, en in action_labels.values())

    # API disposition codes are mapped to the UI's translated action labels.
    assert {"accept", "decline", "needEvidence"} <= locale_keys[0]
    assert {"accept", "decline", "needEvidence"} <= locale_keys[1]
    disposition_match = re.search(r"const dispositionLabels=\{(.*?)\};", admin_html)
    assert disposition_match, "Review UI must define decision disposition labels"
    assert all(
        f"{code}:t.{label}" in disposition_match.group(1)
        for code, label in (
            ("accepted", "accept"),
            ("rejected", "decline"),
            ("needs_more_evidence", "needEvidence"),
        )
    )



def test_reviewed_plan_classifies_latest_decisions_without_authorizing_apply():
    snapshot = {"remediation_plan": {"items": [
        {"proposal_id": "accepted", "action": "split_candidate_manual_review"},
        {"proposal_id": "rejected", "action": "merge_candidate_manual_review"},
        {"proposal_id": "evidence", "action": "manual_review"},
        {"proposal_id": "pending", "action": "keep_existing_link_candidate"},
    ]}}
    decisions = {
        "accepted": {"disposition": "accepted", "reason": "Confirmed split."},
        "rejected": {"disposition": "rejected"},
        "evidence": {"disposition": "needs_more_evidence"},
    }

    result = _build_reviewed_remediation_plan(snapshot, decisions)

    assert [item["review_status"] for item in result["items"]] == [
        "accepted_by_reviewer",
        "rejected_by_reviewer",
        "needs_more_evidence",
        "pending_review",
    ]
    assert result["summary"]["decided_items"] == 3
    assert result["summary"]["pending_review"] == 1
    assert result["writes_to_catalog"] is False
    assert result["catalog_apply_authorized"] is False
    assert result["summary"]["safe_to_apply_automatically"] is False


from app.models import (
    Casting, CatalogIdentifier, Evidence, EvidenceRelease, IdentifierType,
    Release, ReleaseIdentifier, Source, SourceRecord,
    CastingGroupingReviewDecision, CastingGroupingReviewSession,
)


def make_review_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE product_lines (id TEXT PRIMARY KEY, name TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE catalog_nodes (id TEXT PRIMARY KEY, parent_id TEXT, node_type TEXT NOT NULL, product_line_id TEXT, release_id TEXT)"
        )
    with Session(engine) as db:
        casting = Casting(name="Mazda Autozam", status="candidate")
        db.add(casting)
        db.flush()
        release = Release(
            id="review-release-1", casting_id=casting.id, name="Mazda Autozam",
            catalog_year=2024, status="candidate",
        )
        sku_type = IdentifierType(code="sku", label="SKU")
        db.add_all([release, sku_type])
        db.flush()
        sku = CatalogIdentifier(
            identifier_type_id=sku_type.id, value="HRY51", normalized_value="HRY51"
        )
        db.add(sku)
        db.flush()
        db.add(ReleaseIdentifier(
            release_id=release.id, identifier_id=sku.id, role="primary"
        ))
        source = Source(name="Review test source", source_type="test")
        db.add(source)
        db.flush()
        source_record = SourceRecord(
            source_id=source.id, record_type="catalog_item", raw_data={}
        )
        db.add(source_record)
        db.flush()
        evidence = Evidence(
            source_record_id=source_record.id,
            attribute_name="collector_number",
            observed_value="001",
            review_status="pending",
        )
        db.add(evidence)
        db.flush()
        db.add(EvidenceRelease(
            evidence_id=evidence.id, release_id=release.id, role="about"
        ))
        db.execute(
            text("INSERT INTO product_lines (id, name) VALUES ('line-mainline', 'Mainline')")
        )
        db.execute(
            text("INSERT INTO catalog_nodes (id, node_type, product_line_id) VALUES ('line-mainline', 'product_line', 'line-mainline')")
        )
        db.execute(
            text("INSERT INTO catalog_nodes (id, parent_id, node_type) VALUES ('year-2024', 'line-mainline', 'year')")
        )
        db.execute(
            text("INSERT INTO catalog_nodes (id, parent_id, node_type) VALUES ('series-1', 'year-2024', 'series')")
        )
        db.execute(
            text("INSERT INTO catalog_nodes (id, parent_id, node_type, release_id) VALUES ('release-node-1', 'series-1', 'release', 'review-release-1')")
        )
        db.commit()
    return engine


def install_review_db_override(engine):
    def override_get_db():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = override_get_db


def test_review_session_persists_snapshot_and_append_only_decision_history():
    engine = make_review_engine()
    install_review_db_override(engine)
    client = TestClient(app)
    try:
        created = client.post(
            "/castings/grouping-review-sessions/from-catalog",
            json={"product_line": "Mainline", "catalog_year": 2024},
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["writes_to_catalog"] is False
        assert payload["stale"] is False
        assert payload["reviewed_plan"]["summary"]["pending_review"] == 1
        assert payload["reviewed_plan"]["catalog_apply_authorized"] is False
        session_id = payload["session_id"]
        proposal_id = payload["snapshot"]["remediation_plan"]["items"][0]["proposal_id"]

        first = client.post(
            f"/castings/grouping-review-sessions/{session_id}/decisions",
            json={
                "proposal_id": proposal_id,
                "disposition": "needs_more_evidence",
                "reviewer_label": "operator",
                "reason": "Evidence is still pending.",
            },
        )
        assert first.status_code == 200
        first_decision = first.json()["decision"]
        assert first_decision["previous_decision_id"] is None

        second = client.post(
            f"/castings/grouping-review-sessions/{session_id}/decisions",
            json={
                "proposal_id": proposal_id,
                "disposition": "accepted",
                "reviewer_label": "operator",
                "reason": "Reviewed again.",
            },
        )
        assert second.status_code == 200
        assert second.json()["decision"]["previous_decision_id"] == first_decision["id"]

        history = client.get(
            f"/castings/grouping-review-sessions/{session_id}/decisions"
        )
        assert history.status_code == 200
        assert history.json()["total"] == 2
        assert [item["disposition"] for item in history.json()["items"]] == [
            "needs_more_evidence", "accepted"
        ]

        detail = client.get(f"/castings/grouping-review-sessions/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["decisions"][0]["disposition"] == "accepted"
        reviewed_plan = detail.json()["reviewed_plan"]
        assert reviewed_plan["mode"] == "reviewed_report_only"
        assert reviewed_plan["writes_to_catalog"] is False
        assert reviewed_plan["catalog_apply_authorized"] is False
        assert reviewed_plan["summary"]["accepted_by_reviewer"] == 1
        assert reviewed_plan["summary"]["decided_items"] == 1
        assert reviewed_plan["items"][0]["review_status"] == "accepted_by_reviewer"
        assert reviewed_plan["items"][0]["review_reason"] == "Reviewed again."

        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(CastingGroupingReviewSession)) == 1
            assert db.scalar(select(func.count()).select_from(CastingGroupingReviewDecision)) == 2
            assert db.scalar(select(func.count()).select_from(Casting)) == 1
            assert db.scalar(select(func.count()).select_from(Release)) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_review_session_rejects_unknown_proposal_and_stale_decisions():
    engine = make_review_engine()
    install_review_db_override(engine)
    client = TestClient(app)
    try:
        created = client.post(
            "/castings/grouping-review-sessions/from-catalog",
            json={"product_line": "Mainline", "catalog_year": 2024},
        )
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        unknown = client.post(
            f"/castings/grouping-review-sessions/{session_id}/decisions",
            json={
                "proposal_id": "not-in-snapshot",
                "disposition": "accepted",
                "reviewer_label": "operator",
            },
        )
        assert unknown.status_code == 404

        with Session(engine) as db:
            evidence = db.scalar(select(Evidence))
            evidence.observed_value = "002"
            db.commit()

        stale_detail = client.get(
            f"/castings/grouping-review-sessions/{session_id}"
        )
        assert stale_detail.status_code == 200
        assert stale_detail.json()["stale"] is True

        stale_decision = client.post(
            f"/castings/grouping-review-sessions/{session_id}/decisions",
            json={
                "proposal_id": created.json()["snapshot"]["remediation_plan"]["items"][0]["proposal_id"],
                "disposition": "accepted",
                "reviewer_label": "operator",
            },
        )
        assert stale_decision.status_code == 409
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(CastingGroupingReviewDecision)) == 0
    finally:
        app.dependency_overrides.pop(get_db, None)

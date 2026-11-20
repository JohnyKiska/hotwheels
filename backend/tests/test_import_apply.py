from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.importers.apply import apply_import_observation
from app.models import ChangeLog, Casting, Evidence, SourceRecord


def _observation(value="'87 Dodge D100", source_row=7):
    return {
        "source": {
            "code": "mainline_checklist",
            "record_type": "mainline_checklist_row",
            "format": "tsv",
            "record_url": "https://example.test/mainline.tsv",
            "external_id": None,
        },
        "subject_hints": {"name": value, "catalog_year": 2024},
        "claims": [
            {"attribute": "model_name", "value": value, "raw_value": value, "source_field": "Model"},
            {"attribute": "catalog_year", "value": 2024, "raw_value": "2024", "source_field": "Year"},
        ],
        "identifier_hints": [{"type_code": "toy_number", "raw_value": "038"}],
        "raw": {"source_row": source_row, "source_values": {"Model": value}},
        "review_status": "candidate",
    }


def test_apply_import_observation_is_idempotent_and_evidence_only():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            first = apply_import_observation(session, _observation(), actor_id="reviewer-1")
            session.commit()
            replay = apply_import_observation(session, _observation(), actor_id="reviewer-1")
            session.commit()

            assert first["record_created"] is True
            assert first["evidence_created"] == 2
            assert replay["record_created"] is False
            assert replay["evidence_created"] == 0
            assert replay["source_record_id"] == first["source_record_id"]
            assert session.scalar(select(func.count()).select_from(SourceRecord)) == 1
            assert session.scalar(select(func.count()).select_from(Evidence)) == 2
            assert session.scalar(select(func.count()).select_from(ChangeLog)) == 1
            assert session.scalar(select(func.count()).select_from(Casting)) == 0
            assert first["writes_to_catalog_entities"] is False
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_changed_snapshot_creates_new_source_record_not_overwrite():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            first = apply_import_observation(session, _observation(), actor_id="reviewer-1")
            second = apply_import_observation(
                session, _observation(value="'87 Dodge D100 (2nd Color)"), actor_id="reviewer-1"
            )
            session.commit()

            assert first["source_record_id"] != second["source_record_id"]
            assert session.scalar(select(func.count()).select_from(SourceRecord)) == 2
            assert session.scalar(select(func.count()).select_from(Evidence)) == 4
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_unknown_source_code_is_rejected_without_writes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            observation = _observation()
            observation["source"]["code"] = "arbitrary-client-source"
            try:
                apply_import_observation(session, observation, actor_id="reviewer-1")
            except ValueError as exc:
                assert "Unsupported import source code" in str(exc)
            else:
                raise AssertionError("Unknown source code should be rejected")
            assert session.scalar(select(func.count()).select_from(SourceRecord)) == 0
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Casting, Release, SourceRecord, Evidence, Conflict


def make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def override_database(engine):
    def override_get_db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db


def test_pipeline_preview_returns_parser_observation_and_match_without_writes():
    engine = make_engine()
    with Session(engine) as session:
        casting = Casting(name="Synthetic Skyline", status="confirmed")
        session.add(casting)
        session.flush()
        release = Release(
            casting_id=casting.id,
            name="Synthetic Skyline",
            catalog_year=2026,
            status="candidate",
        )
        session.add(release)
        session.commit()

    override_database(engine)
    try:
        response = TestClient(app).post("/imports/preview", json={
            "source": "mainline_tsv",
            "catalog_year": 2026,
            "text": "Toy #\tCatalog #\tName\tSeries\nABC12\tJHW01\tSynthetic Skyline\tHW J-Imports\n",
        })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract"] == "hw_catalog.import_pipeline_preview"
    assert payload["mode"] == "preview_only"
    assert payload["writes_to_catalog"] is False
    assert payload["records_available"] == 1
    assert payload["observation"]["subject_hints"]["catalog_year"] == 2026
    assert payload["matching"]["status"] == "strong_candidate"
    assert payload["claim_diff"] is None

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Release)) == 1
        assert session.scalar(select(func.count()).select_from(SourceRecord)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 0
        assert session.scalar(select(func.count()).select_from(Conflict)) == 0


def test_pipeline_preview_with_explicit_release_returns_attribute_diff():
    engine = make_engine()
    with Session(engine) as session:
        casting = Casting(name="Synthetic Skyline", status="confirmed")
        session.add(casting)
        session.flush()
        release = Release(
            casting_id=casting.id,
            name="Synthetic Skyline",
            catalog_year=2026,
            assortment_number="JHW01",
            status="candidate",
        )
        session.add(release)
        session.commit()
        release_id = release.id

    override_database(engine)
    try:
        response = TestClient(app).post("/imports/preview", json={
            "source": "mainline_tsv",
            "catalog_year": 2026,
            "selected_release_id": release_id,
            "text": "Toy #\tCatalog #\tName\tSeries\nABC12\tJHW01\tSynthetic Skyline\tHW J-Imports\n",
        })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_release"]["id"] == release_id
    assert payload["claim_diff"]["selected_entity"]["entity_id"] == release_id
    statuses = {item["attribute"]: item["status"] for item in payload["claim_diff"]["claims"]}
    assert statuses["model_name"] == "same"
    assert statuses["catalog_year"] == "same"
    assert statuses["assortment_number"] == "same"
    assert statuses["series_name"] == "new_evidence"
    assert payload["writes_to_catalog"] is False


def test_pipeline_preview_rejects_out_of_range_record_index():
    engine = make_engine()
    override_database(engine)
    try:
        response = TestClient(app).post("/imports/preview", json={
            "source": "mainline_tsv",
            "catalog_year": 2026,
            "record_index": 4,
            "text": "Toy #\tCatalog #\tName\nABC12\tJHW01\tSynthetic Skyline\n",
        })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422
    assert "out of range" in response.json()["detail"]


def test_pipeline_preview_returns_404_for_unknown_explicit_release():
    engine = make_engine()
    override_database(engine)
    try:
        response = TestClient(app).post("/imports/preview", json={
            "source": "mainline_tsv",
            "catalog_year": 2026,
            "selected_release_id": "missing-release",
            "text": "Toy #\tCatalog #\tName\nABC12\tJHW01\tSynthetic Skyline\n",
        })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404


def test_pipeline_preview_accepts_saved_fandom_yearly_html():
    engine = make_engine()
    override_database(engine)
    html = """<title>List of 2025 Hot Wheels</title>
    <link rel="canonical" href="https://example.invalid/list-2025">
    <p>For 2025, the Hot Wheels mainline is numbered 1 through 250.</p>
    <table class="sortable wikitable">
      <tr><th>Toy #</th><th>Col.#</th><th>Model Name</th><th>Series</th><th>Series #</th></tr>
      <tr><td>ABC12</td><td>141</td><td>Synthetic Skyline</td><td>HW J-Imports</td><td>5/5</td></tr>
    </table>"""
    try:
        response = TestClient(app).post("/imports/preview", json={
            "source": "fandom_html",
            "catalog_year": 2025,
            "text": html,
        })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["code"] == "fandom"
    assert payload["observation"]["subject_hints"]["catalog_year"] == 2025
    assert payload["observation"]["subject_hints"]["collector_number"] == "141"


def test_pipeline_preview_accepts_saved_all_hot_wheels_html():
    engine = make_engine()
    override_database(engine)
    html = """<html><head>
      <title>SYN25 Synthetic Coupe</title>
      <link rel="canonical" href="https://example.invalid/car/2026/fast-furious/syn25/model">
    </head><body>
      <span class="bg-primary">chase</span>
      <h1>Synthetic Coupe</h1>
      <p>Fast &amp; Furious · Synthetic Series · #2/5</p>
      <div><div>SKU</div><div>SYN25</div></div>
      <div><div>Release year</div><div>2026</div></div>
      <div><div>Scale</div><div>1/64</div></div>
      <div><div>Base material</div><div>Plastic</div></div>
      <div><div>Series index</div><div>2/5</div></div>
      <div><div>Mainline #</div><div>-</div></div>
      <h3>Wheels</h3><div><span><span class="font-mono">5SP</span>5-Spoke</span></div>
      <h3>Colors</h3><div><div><div><div><span>color:</span><span>Blue</span></div></div></div></div>
      <h3>Tags</h3><div><a href="/browse?q=synthetic">synthetic</a></div>
    </body></html>"""
    try:
        response = TestClient(app).post("/imports/preview", json={
            "source": "all_hot_wheels_html",
            "expected_year": 2026,
            "text": html,
        })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["code"] == "all_hot_wheels"
    assert payload["observation"]["subject_hints"]["release_year"] == 2026
    assert payload["observation"]["subject_hints"]["catalog_year"] is None


def test_pipeline_preview_requires_catalog_year_for_mainline_sources():
    engine = make_engine()
    override_database(engine)
    try:
        response = TestClient(app).post("/imports/preview", json={
            "source": "mainline_tsv",
            "text": "Toy #\\tCatalog #\\tName\\nABC12\\tJHW01\\tSynthetic Skyline\\n",
        })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422

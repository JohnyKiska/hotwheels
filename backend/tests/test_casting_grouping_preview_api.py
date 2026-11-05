from fastapi.testclient import TestClient

from app.main import app


def test_casting_grouping_preview_endpoint_returns_read_only_proposals():
    response = TestClient(app).post("/castings/grouping-preview", json={
        "records": [
            {
                "record_id": "then-and-now",
                "release_id": "release-1",
                "product_line": "Mainline",
                "catalog_year": 2024,
                "collector_number_claims": [{"value": "191", "source_record_id": "source-1"}],
                "sku": ["HTC65"],
                "model_name": "Nissan Skyline 2000GT-R LBWK",
            },
            {
                "record_id": "tooned",
                "release_id": "release-2",
                "product_line": "Mainline",
                "catalog_year": 2024,
                "collector_number_claims": [{"value": "213", "source_record_id": "source-2"}],
                "sku": ["HRY85"],
                "model_name": "Nissan Skyline 2000GT-R LBWK",
            },
        ],
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract"] == "hw_catalog.casting_grouping_preview"
    assert payload["mode"] == "preview_only"
    assert payload["writes_to_catalog"] is False
    assert len(payload["groups"]) == 2


def test_casting_grouping_preview_endpoint_rejects_duplicate_record_ids():
    response = TestClient(app).post("/castings/grouping-preview", json={
        "records": [
            {"record_id": "duplicate", "product_line": "Mainline",
             "catalog_year": 2024, "collector_number_claims": ["001"]},
            {"record_id": "duplicate", "product_line": "Mainline",
             "catalog_year": 2024, "collector_number_claims": ["002"]},
        ],
    })

    assert response.status_code == 422

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_mainline_preview_api_returns_candidates_without_writing_catalog():
    response = client.post(
        "/imports/mainline/preview",
        json={
            "catalog_year": 2026,
            "text": (
                "Toy #\tCatalog #\tName\tSeries\n"
                "ABC12\tJHW01\tNissan Skyline\tHW J-Imports\n"
                "3/10 Treasure Hunt\n"
            ),
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["importer"] == "mainline"
    assert result["mode"] == "preview_only"
    assert result["writes_to_catalog"] is False
    assert result["summary"]["records_found"] == 1
    assert result["records"][0]["toy_number"] == "ABC12"
    assert result["records"][0]["rarity"] == "Treasure Hunt (TH)"


def test_mainline_preview_api_rejects_out_of_range_year():
    response = client.post(
        "/imports/mainline/preview",
        json={"catalog_year": 1900, "text": "ABC12\tJHW01\tNissan Skyline"},
    )

    assert response.status_code == 422


def test_mainline_preview_api_rejects_empty_text():
    response = client.post(
        "/imports/mainline/preview",
        json={"catalog_year": 2026, "text": "  "},
    )

    assert response.status_code == 422

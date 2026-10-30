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



def test_fandom_html_preview_api_returns_read_only_candidates():
    response = client.post(
        "/imports/mainline/fandom-html-preview",
        json={
            "catalog_year": 2025,
            "text": """<title>List of 2025 Hot Wheels</title>
            <table class="sortable wikitable">
            <tr><th>Toy #</th><th>Col.#</th><th>Model Name</th><th>Series</th><th>Series #</th><th>Photo</th></tr>
            <tr><td>JBC25</td><td>141</td><td>'85 Honda City Turbo II</td>
            <td>HW J-Imports Treasure Hunt</td><td>5/5</td><td></td></tr>
            </table>""",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["writes_to_catalog"] is False
    assert result["source_format"] == "fandom_yearly_html"
    assert result["records"][0]["collector_number"] == "141"
    assert result["records"][0]["rarity"] == "Treasure Hunt (TH)"


def test_fandom_html_preview_api_rejects_non_list_html():
    response = client.post(
        "/imports/mainline/fandom-html-preview",
        json={"catalog_year": 2025, "text": "<title>Single car page</title>"},
    )

    assert response.status_code == 422

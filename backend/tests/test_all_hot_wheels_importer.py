from fastapi.testclient import TestClient

from app.importers.all_hot_wheels import preview_all_hot_wheels_html
from app.main import app


client = TestClient(app)


def _page(*, category="mainline", special="treasure hunt", sku="JBC25",
          year="2025", mainline_number="141", series="HW J-IMPORT",
          series_index="5/5", summary_index="5/5"):
    category_label = {
        "mainline": "Mainline",
        "fast-furious": "Fast & Furious",
        "character-cars": "Character Cars",
        "themed-entertainment": "Themed Entertainment",
        "car-culture": "Car Culture",
        "pop-culture": "Pop Culture",
    }[category]
    summary = (
        f"<p>{category_label} · {series} · #{summary_index}</p>"
        if summary_index is not None else ""
    )
    return f"""<!doctype html>
    <html><head>
      <title>{sku} '85 HONDA CITY TURBO II Hot Wheels ({year}) | All Hot Wheels</title>
      <link rel="canonical" href="https://allhotwheels.com/car/{year}/{category}/{sku.lower()}/model"/>
    </head><body>
      <div class="flex items-center gap-2">
        <span class="bg-primary">{special}</span>
        <span>1/64</span>
      </div>
      <h1>'85 HONDA CITY TURBO II</h1>
      <p>City</p>
      {summary}
      <div class="mt-3"><span class="bg-brand-indigo"> {series} </span></div>
      <div class="grid">
        <div class="bg-card"><div>SKU</div><div>{sku}</div></div>
        <div class="bg-card"><div>Release year</div><div>{year}</div></div>
        <div class="bg-card"><div>Scale</div><div>1/64</div></div>
        <div class="bg-card"><div>Base material</div><div>Plastic</div></div>
        <div class="bg-card"><div>Series index</div><div>{series_index}</div></div>
        <div class="bg-card"><div>Mainline #</div><div>{mainline_number}</div></div>
      </div>
      <h3>Wheels</h3>
      <div><span><span class="font-mono">5SP</span>5-Spoke</span></div>
      <h3>Colors</h3>
      <div class="space-y-3">
        <div>
          <div>body</div>
          <div>
            <div><span>color:</span><span>Blue</span></div>
            <div><span>detailed:</span><span>Turquoise</span></div>
            <div><span>source:</span><span>Turquoise</span></div>
            <div><span>premium:</span><span>Spectraflame</span></div>
          </div>
        </div>
        <div>
          <div>interior</div>
          <div>
            <div><span>color:</span><span>Black</span></div>
            <div><span>detailed:</span><span>Black</span></div>
          </div>
        </div>
        <div>
          <div>base</div>
          <div>
            <div><span>color:</span><span>Black</span></div>
            <div><span>source:</span><span>Black</span></div>
          </div>
        </div>
        <div>
          <div>window</div>
          <div><div><span>source:</span><span>Clear (See-Through)</span></div></div>
        </div>
      </div>
      <h3>Tags</h3>
      <div><a href="/browse?q=turbo">turbo</a><a href="/browse?q=hatchback">hatchback</a></div>
    </body></html>"""


def test_all_hot_wheels_parser_extracts_labelled_fields_and_provenance():
    result = preview_all_hot_wheels_html(_page(), expected_year=2025)

    assert result["importer"] == "all_hot_wheels"
    assert result["mode"] == "preview_only"
    assert result["writes_to_catalog"] is False
    record = result["records"][0]
    assert record["toy_number"] == "JBC25"
    assert record["name"] == "'85 HONDA CITY TURBO II"
    assert record["category"] == "Mainline"
    assert record["special_label"] == "treasure hunt"
    assert record["mainline_number"] == 141
    assert record["series_index"] == 5
    assert record["series_total"] == 5
    assert record["wheels"] == [{"code": "5SP", "name": "5-Spoke"}]
    assert record["colors"] == [
        {
            "component": "body",
            "color": "Blue",
            "detailed": "Turquoise",
            "source": "Turquoise",
            "finish": "Spectraflame",
        },
        {
            "component": "interior",
            "color": "Black",
            "detailed": "Black",
        },
        {
            "component": "base",
            "color": "Black",
            "source": "Black",
        },
        {
            "component": "window",
            "source": "Clear (See-Through)",
        },
    ]
    assert record["tags"] == ["turbo", "hatchback"]
    assert record["source_fields"]["mainline_number"] == "Mainline #"
    assert record["source_values"]["Series index"] == "5/5"
    assert record["mainline_number_raw"] == "141"
    assert record["mainline_number_source"] == "Mainline #"
    assert record["mainline_total"] is None
    assert record["mainline_total_source"] is None
    assert record["source_url"] == "https://allhotwheels.com/car/2025/mainline/jbc25/model"


def test_all_hot_wheels_preserves_chase_without_normalizing_to_treasure_hunt():
    result = preview_all_hot_wheels_html(
        _page(category="fast-furious", special="chase", sku="JHW68",
              year="2026", mainline_number="-", series="Fast & Furious Premium Mix 1"),
        expected_year=2026,
    )
    record = result["records"][0]
    assert record["category"] == "Fast & Furious"
    assert record["special_label"] == "chase"
    assert record["mainline_number"] is None


def test_all_hot_wheels_rejects_expected_year_mismatch():
    try:
        preview_all_hot_wheels_html(_page(), expected_year=2026)
    except ValueError as exc:
        assert "2025" in str(exc)
    else:
        raise AssertionError("expected year mismatch to be rejected")


def test_all_hot_wheels_rejects_non_card_html():
    try:
        preview_all_hot_wheels_html("<title>List of Hot Wheels</title>")
    except ValueError as exc:
        assert "h1" in str(exc)
    else:
        raise AssertionError("non-card HTML should be rejected")


def test_all_hot_wheels_preview_api_is_read_only():
    response = client.post(
        "/imports/all-hot-wheels/html-preview",
        json={"expected_year": 2025, "text": _page()},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["writes_to_catalog"] is False
    assert result["records"][0]["toy_number"] == "JBC25"


def test_all_hot_wheels_preview_api_rejects_invalid_html():
    response = client.post(
        "/imports/all-hot-wheels/html-preview",
        json={"expected_year": 2025, "text": "<title>Not a car page</title>"},
    )
    assert response.status_code == 422


def test_all_hot_wheels_preserves_standalone_series_index_without_inventing_total():
    result = preview_all_hot_wheels_html(
        _page(
            category="car-culture",
            special="chase",
            sku="BL018",
            year="2026",
            mainline_number="-",
            series="2026 Car Culture Deutschland Design",
            series_index="95",
            summary_index=None,
        ),
        expected_year=2026,
    )

    record = result["records"][0]
    assert record["category"] == "Car Culture"
    assert record["series_index"] == 95
    assert record["series_total"] is None
    assert record["series_index_raw"] == "95"
    assert record["mainline_number"] is None
    assert record["mainline_number_raw"] == "-"
    assert record["mainline_total"] is None
    assert record["source_values"]["Series index"] == "95"
    assert result["issues"] == []


def test_all_hot_wheels_flags_invalid_series_fraction_and_preserves_raw_value():
    result = preview_all_hot_wheels_html(
        _page(
            category="car-culture",
            special="chase",
            sku="JKF45",
            year="2026",
            mainline_number="-",
            series="2026 Car Culture Deutschland Design",
            series_index="0/5",
            summary_index="0/5",
        ),
        expected_year=2026,
    )

    record = result["records"][0]
    assert record["series_index"] is None
    assert record["series_total"] is None
    assert record["series_index_raw"] == "0/5"
    issue = next(issue for issue in result["issues"] if issue["code"] == "invalid_series_fraction")
    assert issue["severity"] == "warning"
    assert "0/5" in issue["message"]
    assert result["summary"]["warnings"] == 1
    assert result["summary"]["ready_for_review"] is True

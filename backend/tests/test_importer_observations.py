import pytest

from app.importers.all_hot_wheels import preview_all_hot_wheels_html
from app.importers.mainline import preview_mainline_fandom_html, preview_mainline_tsv
from app.importers.observations import preview_to_observations


def test_mainline_tsv_preview_maps_to_shared_observation_without_writes():
    preview = preview_mainline_tsv(
        "Toy #\tCatalog #\tName\tSeries\n"
        "ABC12\tJHW01\tSynthetic Skyline\tHW J-Imports\n"
        "3/10 Treasure Hunt\n",
        2026,
    )

    result = preview_to_observations(preview)

    assert result["contract_version"] == 1
    assert result["writes_to_catalog"] is False
    assert result["source"]["code"] == "mainline_checklist"
    observation = result["observations"][0]
    assert observation["subject_hints"]["catalog_year"] == 2026
    assert observation["identifier_hints"] == [{
        "type_code": "toy_number",
        "raw_value": "ABC12",
        "source_field": "Toy #",
    }]
    claims = {claim["attribute"]: claim for claim in observation["claims"]}
    assert claims["model_name"]["value"] == "Synthetic Skyline"
    assert claims["series_index"]["value"] == 3
    assert claims["rarity"]["value"] == "Treasure Hunt (TH)"
    assert observation["raw"]["raw_text"].startswith("ABC12")


def test_fandom_preview_keeps_collector_number_separate_from_mainline_number():
    html = """<title>List of 2025 Hot Wheels</title>
    <link rel="canonical" href="https://example.invalid/list-2025">
    <p>For 2025, the Hot Wheels mainline is numbered 1 through 250.</p>
    <table class="sortable wikitable">
      <tr><th>Toy #</th><th>Col.#</th><th>Model Name</th><th>Series</th><th>Series #</th></tr>
      <tr><td>ABC12</td><td>141</td><td>Synthetic Skyline</td><td>HW J-Imports</td><td>5/5</td></tr>
    </table>"""

    result = preview_to_observations(preview_mainline_fandom_html(html, 2025))

    observation = result["observations"][0]
    assert observation["source"]["code"] == "fandom"
    assert observation["source"]["record_url"] == "https://example.invalid/list-2025"
    claims = {claim["attribute"]: claim for claim in observation["claims"]}
    assert claims["collector_number"]["value"] == "141"
    assert claims["mainline_number"]["value"] == 141
    assert claims["collector_number"]["attribute"] != claims["mainline_number"]["attribute"]


def test_all_hot_wheels_preview_preserves_chase_and_separates_release_year():
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
      <h3>Colors</h3><div><div><div>body</div><div><div><span>color:</span><span>Blue</span></div></div></div></div>
      <h3>Tags</h3><div><a href="/browse?q=synthetic">synthetic</a></div>
    </body></html>"""

    preview = preview_all_hot_wheels_html(html, expected_year=2026)
    observation = preview_to_observations(preview)["observations"][0]
    claims = {claim["attribute"]: claim for claim in observation["claims"]}

    assert observation["source"]["code"] == "all_hot_wheels"
    assert observation["subject_hints"]["catalog_year"] is None
    assert observation["subject_hints"]["release_year"] == 2026
    assert observation["identifier_hints"][0]["type_code"] == "sku"
    assert claims["special_label"]["value"] == "chase"
    assert "mainline_number" not in claims


def test_adapter_rejects_any_result_that_is_not_explicitly_read_only():
    with pytest.raises(ValueError, match="read-only"):
        preview_to_observations({
            "importer": "mainline",
            "mode": "apply",
            "writes_to_catalog": True,
            "records": [],
        })


def test_adapter_rejects_unknown_source_formats():
    with pytest.raises(ValueError, match="Unsupported importer"):
        preview_to_observations({
            "importer": "unknown",
            "mode": "preview_only",
            "writes_to_catalog": False,
            "records": [],
        })

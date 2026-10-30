from app.importers.mainline import preview_mainline_tsv


def test_mainline_preview_parses_converter_rows_and_continuation_metadata():
    text = (
        "Toy #\tCatalog #\tName\tSeries\n"
        "ABC12\tJHW01\tNissan Skyline\tHW J-Imports\n"
        "3/10 Treasure Hunt\n"
        "DEF34\tJHW02\tHonda Civic\tHW J-Imports\n"
        "New for 2026\n"
    )

    result = preview_mainline_tsv(text, 2026)

    assert result["mode"] == "preview_only"
    assert result["writes_to_catalog"] is False
    assert result["summary"] == {
        "records_found": 2,
        "errors": 0,
        "warnings": 0,
        "ready_for_review": True,
    }
    first, second = result["records"]
    assert first["toy_number"] == "ABC12"
    assert first["assortment_number"] == "JHW01"
    assert first["name"] == "Nissan Skyline"
    assert first["series_name"] == "HW J-Imports"
    assert first["series_index"] == 3
    assert first["series_total"] == 10
    assert first["rarity"] == "Treasure Hunt (TH)"
    assert "Treasure Hunt" in first["notes"]
    assert second["name"] == "Honda Civic"
    assert second["catalog_year"] == 2026
    assert "New for 2026" in second["notes"]


def test_duplicate_toy_numbers_are_flagged_but_never_merged():
    text = (
        "ABC12\tJHW01\tNissan Skyline\tHW J-Imports\n"
        "ABC12\tJHW99\tDifferent model\tHW J-Imports\n"
    )

    result = preview_mainline_tsv(text, 2025)

    assert len(result["records"]) == 2
    duplicate_issue = next(
        issue for issue in result["issues"]
        if issue["code"] == "duplicate_toy_number"
    )
    assert duplicate_issue["different_names"] is True
    assert duplicate_issue["rows"] == [1, 2]
    assert result["summary"]["warnings"] == 1


def test_invalid_series_fraction_is_reported_and_not_assumed():
    result = preview_mainline_tsv(
        "ABC12\tJHW01\tNissan Skyline\tHW J-Imports 12/10\n",
        2025,
    )

    assert result["records"][0]["series_index"] is None
    assert result["records"][0]["series_total"] is None
    assert any(issue["code"] == "invalid_series_fraction" for issue in result["issues"])


def test_empty_input_and_out_of_range_year_are_rejected():
    import pytest

    with pytest.raises(ValueError, match="чек-листа"):
        preview_mainline_tsv("  \n", 2025)
    with pytest.raises(ValueError, match="диапазоне"):
        preview_mainline_tsv("ABC12\tJHW01\tNissan Skyline", 1900)


def test_unrecognized_nonempty_input_returns_actionable_preview_issue():
    result = preview_mainline_tsv("This is not a tab-separated checklist", 2026)

    assert result["records"] == []
    assert result["summary"]["ready_for_review"] is False
    assert any(issue["code"] == "no_records" for issue in result["issues"])



def test_fandom_yearly_html_preview_extracts_collector_number_and_treasure_hunt():
    from app.importers.mainline import preview_mainline_fandom_html

    text = """<!doctype html>
    <html><head><title>List of 2025 Hot Wheels | Hot Wheels Wiki</title></head>
    <body><table class="sortable wikitable">
    <tr><th>Toy #</th><th>Col.#</th><th>Model Name</th><th>Series</th><th>Series #</th><th>Photo</th></tr>
    <tr><td>JBC25</td><td>141</td><td>'85 Honda City Turbo II</td>
    <td>HW J-Imports Treasure Hunt</td><td>5/5</td><td></td></tr>
    <tr><td>HYW18</td><td>001</td><td>Mazda MX-5 Miata</td>
    <td>HW Dream Garage New for 2025!</td><td>2/5</td><td></td></tr>
    </table></body></html>"""

    result = preview_mainline_fandom_html(text, 2025)

    assert result["mode"] == "preview_only"
    assert result["writes_to_catalog"] is False
    assert result["source_format"] == "fandom_yearly_html"
    assert result["summary"]["records_found"] == 2
    first, second = result["records"]
    assert first["toy_number"] == "JBC25"
    assert first["collector_number"] == "141"
    assert first["assortment_number"] is None
    assert first["name"] == "'85 Honda City Turbo II"
    assert first["series_name"] == "HW J-Imports"
    assert first["series_index"] == 5
    assert first["series_total"] == 5
    assert first["rarity"] == "Treasure Hunt (TH)"
    assert second["collector_number"] == "001"
    assert second["series_name"] == "HW Dream Garage"
    assert "New for 2025" in second["notes"]


def test_fandom_html_preview_rejects_wrong_year_and_model_detail_pages():
    import pytest
    from app.importers.mainline import preview_mainline_fandom_html

    with pytest.raises(ValueError, match="выбран год"):
        preview_mainline_fandom_html(
            '<title>List of 2025 Hot Wheels</title><table class="sortable wikitable"></table>',
            2026,
        )
    with pytest.raises(ValueError, match="основная таблица Fandom"):
        preview_mainline_fandom_html(
            '<title>JHW68 Mitsubishi Eclipse</title><p>Individual model page</p>',
            2026,
        )

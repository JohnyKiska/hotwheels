from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "import_mainline.py"
SPEC = importlib.util.spec_from_file_location("import_mainline_cli", SCRIPT_PATH)
CLI = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CLI)


def test_parse_fandom_table_preserves_sku_annotations_and_series_index():
    html = """
    <html><body><table>
      <tr><th>Toy #</th><th>Col.#</th><th>Model Name</th><th>Series</th><th>Series #</th></tr>
      <tr><td>HTD01</td><td>037</td><td>Ford F-150 Lightning Custom (2nd Color)</td>
          <td>HW Green Speed</td><td>5/10</td></tr>
      <tr><td>HTF81</td><td>098</td><td>Alfa Romeo GTV6 3.0 (2nd Color)</td>
          <td>Red Edition Target Exclusive</td><td>9/12</td></tr>
    </table></body></html>
    """
    snapshot = CLI.parse_fandom_table(html, 2024)

    assert snapshot["year"] == 2024
    assert snapshot["record_count"] == 2
    assert snapshot["records"][0]["toy_number"] == "HTD01"
    assert snapshot["records"][0]["collector_number"] == "037"
    assert snapshot["records"][0]["model_name"] == "Ford F-150 Lightning Custom (2nd Color)"
    assert snapshot["records"][0]["series_name"] == "HW Green Speed"
    assert snapshot["records"][0]["series_number_raw"] == "5/10"


def test_parse_fandom_table_skips_non_sku_rows_and_rejects_empty_result():
    html = """
    <html><body><table>
      <tr><th>Toy #</th><th>Col.#</th><th>Model Name</th><th>Series</th><th>Series #</th></tr>
      <tr><td>Notes</td><td></td><td>Not a model row</td><td></td><td></td></tr>
    </table></body></html>
    """
    try:
        CLI.parse_fandom_table(html, 2024)
    except ValueError as exc:
        assert "no valid SKU rows" in str(exc)
    else:
        raise AssertionError("Expected parser to reject a table with no valid SKU rows")

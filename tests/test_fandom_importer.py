import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

fandom = load("import_fandom_mainline", "scripts/import_fandom_mainline.py")


class FandomImporterTests(unittest.TestCase):
    def test_parses_variant_rows_and_preserves_annotations(self):
        html = """
        <html><body><table class="wikitable">
          <tr><th>Toy #</th><th>Col.#</th><th>Model Name</th><th>Series</th><th>Series #</th><th>Photo</th></tr>
          <tr><td>HYW66</td><td>008</td><td>Mazda Autozam</td><td>HW Dream Garage</td><td>1/5</td><td></td></tr>
          <tr><td>HYY10</td><td>008</td><td>Mazda Autozam (2nd Color - Zamac)</td><td>HW Dream Garage<br/>Walmart Exclusive</td><td>1/5</td><td></td></tr>
        </table></body></html>
        """
        records = fandom.parse_table(html, 2025, "https://example.test/list")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["toy_number"], "HYW66")
        self.assertEqual(records[0]["collector_number"], "008")
        self.assertEqual(records[0]["series_number_raw"], "1/5")
        self.assertEqual(records[1]["series_name"], "HW Dream Garage")
        self.assertEqual(records[1]["source_annotations"]["series"], ["Walmart Exclusive"])

    def test_rejects_page_without_expected_table(self):
        with self.assertRaises(ValueError):
            fandom.parse_table("<html><table><tr><th>Name</th></tr></table></html>",
                               2025, "https://example.test/list")


if __name__ == "__main__":
    unittest.main()

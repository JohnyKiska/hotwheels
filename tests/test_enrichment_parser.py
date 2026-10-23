import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / "scripts" / "enrich_catalog_from_html.py"
spec = importlib.util.spec_from_file_location("enrich_catalog_from_html", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EnrichmentParserTests(unittest.TestCase):
    def test_extracts_sku_scale_wheels_and_color_labels(self):
        html = """
        <html><head>
          <link rel="canonical" href="https://allhotwheels.com/car/2025/mainline/hyw66/mazda-autozam"/>
        </head><body>
          <h1>MAZDA AUTOZAM</h1>
          <main>
            <div>SKU HYW66 Release year 2025 Scale 1/64</div>
            <div><h3>Wheels</h3><div>OR6SP Off-Road 6-Spoke</div></div>
            <div><h3>Colors</h3><div>body color : Red detailed : Red source : Red interior source : Grey (Silver) base color : Black window source : Clear (See-Through)</div></div>
          </main>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.html"
            path.write_text(html, encoding="utf-8")
            result = module.parse_saved_page(path)

        self.assertEqual(result["sku"], "HYW66")
        self.assertEqual(result["source_url"], "https://allhotwheels.com/car/2025/mainline/hyw66/mazda-autozam")
        self.assertEqual(result["release_year"], 2025)
        self.assertEqual(result["scale"], "1/64")
        self.assertIn("OR6SP Off-Road 6-Spoke", result["wheel_description"])
        self.assertIn({"label": "body color", "value": "Red"}, result["color_attributes"])
        self.assertIn({"label": "interior source", "value": "Grey (Silver)"}, result["color_attributes"])
        self.assertIn({"label": "window source", "value": "Clear (See-Through)"}, result["color_attributes"])

    def test_returns_none_without_sku(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-a-car.html"
            path.write_text("<html><body><h1>Example</h1></body></html>", encoding="utf-8")
            self.assertIsNone(module.parse_saved_page(path))


if __name__ == "__main__":
    unittest.main()

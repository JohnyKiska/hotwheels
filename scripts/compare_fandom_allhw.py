#!/usr/bin/env python3
"""Compare a Fandom Mainline snapshot with saved All Hot Wheels HTML pages."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

PARSER_PATH = Path(__file__).with_name("enrich_catalog_from_html.py")
SPEC = importlib.util.spec_from_file_location("allhw_parser", PARSER_PATH)
ALLHW_PARSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ALLHW_PARSER)


def normalize(value):
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def labelled_value(soup: BeautifulSoup, label: str):
    for node in soup.find_all(string=re.compile(rf"^\s*{re.escape(label)}\s*$", re.I)):
        parent = node.parent
        container = parent.parent if parent else None
        if container:
            value = container.get_text(" ", strip=True)
            value = re.sub(rf"^\s*{re.escape(label)}\s*", "", value, flags=re.I).strip()
            if value:
                return value
    return None


def parse_allhw_page(path: Path) -> dict | None:
    parsed = ALLHW_PARSER.parse_saved_page(path)
    if not parsed:
        return None
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    parsed["mainline_number"] = labelled_value(soup, "Mainline #")
    parsed["series_index"] = labelled_value(soup, "Series index")
    parsed["page_title"] = soup.title.get_text(" ", strip=True) if soup.title else None
    return parsed


def compare(fandom: dict, html_dir: Path) -> dict:
    pages = {}
    unreadable = []
    for path in sorted(html_dir.glob("*.html")):
        try:
            page = parse_allhw_page(path)
        except Exception as exc:
            unreadable.append({"source_file": path.name, "error": str(exc)})
            continue
        if page:
            pages.setdefault(page["sku"], []).append(page)

    comparisons = []
    unmatched = []
    ambiguous = []
    for record in fandom.get("records", []):
        sku = record.get("toy_number")
        matches = pages.get(sku, [])
        if not matches:
            unmatched.append({"toy_number": sku, "model_name": record.get("model_name")})
            continue
        if len(matches) > 1:
            ambiguous.append({"toy_number": sku, "page_count": len(matches)})
            continue

        page = matches[0]
        checks = []
        def add_check(field, left, right, method="normalized_exact"):
            if left in (None, "") or right in (None, ""):
                status = "not_comparable"
            elif method == "normalized_exact":
                status = "match" if normalize(left) == normalize(right) else "conflict"
            elif method == "numeric":
                try:
                    status = "match" if int(str(left).strip()) == int(str(right).strip()) else "conflict"
                except (TypeError, ValueError):
                    status = "conflict"
            else:
                status = "match" if str(left).strip() == str(right).strip() else "conflict"
            checks.append({"field": field, "fandom": left, "allhw": right, "status": status})

        add_check("model_name", record.get("model_name"), page.get("source_name"))
        add_check("release_year", fandom.get("year"), page.get("release_year"), "exact")
        add_check("collector_number_vs_mainline_number",
                  record.get("collector_number"), page.get("mainline_number"), "numeric")
        add_check("series_number_vs_series_index",
                  record.get("series_number_raw"), page.get("series_index"), "exact")
        comparisons.append({
            "toy_number": sku,
            "fandom": {
                "model_name": record.get("model_name"),
                "collector_number": record.get("collector_number"),
                "series_name": record.get("series_name"),
                "series_number_raw": record.get("series_number_raw"),
                "source_annotations": record.get("source_annotations"),
            },
            "allhw": {
                "source_name": page.get("source_name"),
                "release_year": page.get("release_year"),
                "mainline_number": page.get("mainline_number"),
                "series_index": page.get("series_index"),
                "wheel_description": page.get("wheel_description"),
                "color_attributes": page.get("color_attributes"),
                "source_url": page.get("source_url"),
                "source_file": page.get("source_file"),
            },
            "checks": checks,
            "review_required": any(item["status"] in {"conflict", "not_comparable"} for item in checks),
        })

    conflicts = sum(
        check["status"] == "conflict"
        for item in comparisons for check in item["checks"]
    )
    not_comparable = sum(
        check["status"] == "not_comparable"
        for item in comparisons for check in item["checks"]
    )
    return {
        "schema_version": 1,
        "comparison": "fandom-mainline-vs-allhw",
        "year": fandom.get("year"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fandom_source": fandom.get("source"),
        "allhw_directory": str(html_dir),
        "summary": {
            "fandom_records": len(fandom.get("records", [])),
            "matched_records": len(comparisons),
            "unmatched_records": len(unmatched),
            "ambiguous_records": len(ambiguous),
            "conflicting_fields": conflicts,
            "not_comparable_fields": not_comparable,
            "unreadable_allhw_pages": len(unreadable),
        },
        "records": comparisons,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "unreadable_pages": unreadable,
        "policy": "Report only. No catalog or collection files are modified.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fandom", required=True, help="JSON snapshot from import_fandom_mainline.py")
    parser.add_argument("--html-dir", default="ALLHW")
    parser.add_argument("--output", default="fandom-allhw-comparison.json")
    args = parser.parse_args()

    fandom = json.loads(Path(args.fandom).read_text(encoding="utf-8"))
    result = compare(fandom, Path(args.html_dir))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote comparison report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

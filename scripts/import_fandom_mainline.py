#!/usr/bin/env python3
"""Import a Hot Wheels yearly Mainline table from the Fandom MediaWiki API.

The importer is read-only with respect to the project catalog. It writes a
source-preserving JSON snapshot for review and never edits collection.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_PAGE = "List_of_{year}_Hot_Wheels"
DEFAULT_API = "https://hotwheels.fandom.com/api.php"
REQUIRED_HEADERS = ("toy #", "col.#", "model name", "series", "series #")
USER_AGENT = "HW-Catalog-Research/1.0 (read-only catalog importer)"


def clean_lines(cell) -> list[str]:
    if cell is None:
        return []
    text = cell.get_text("\n", strip=True)
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def normalized_header(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def find_mainline_table(soup: BeautifulSoup):
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [normalized_header(cell.get_text(" ", strip=True))
                   for cell in rows[0].find_all(["th", "td"], recursive=False)]
        if all(header in headers for header in REQUIRED_HEADERS):
            return table, {header: headers.index(header) for header in REQUIRED_HEADERS}
    raise ValueError("Could not find a table with Toy #, Col.#, Model Name, Series and Series # columns")


def parse_table(html: str, year: int, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table, indexes = find_mainline_table(soup)
    records = []
    for row_number, row in enumerate(table.find_all("tr")[1:], start=2):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) <= max(indexes.values()):
            continue
        toy_lines = clean_lines(cells[indexes["toy #"]])
        col_lines = clean_lines(cells[indexes["col.#"]])
        model_lines = clean_lines(cells[indexes["model name"]])
        series_lines = clean_lines(cells[indexes["series"]])
        series_number_lines = clean_lines(cells[indexes["series #"]])
        if not toy_lines or not model_lines:
            continue

        toy_number = toy_lines[0].upper()
        if not re.fullmatch(r"[A-Z0-9]{4,8}", toy_number):
            continue
        collector_number = col_lines[0] if col_lines else None
        series_name = series_lines[0] if series_lines else None
        records.append({
            "toy_number": toy_number,
            "collector_number": collector_number,
            "model_name": model_lines[0],
            "series_name": series_name,
            "series_number_raw": series_number_lines[0] if series_number_lines else None,
            "source_annotations": {
                "model": model_lines[1:],
                "series": series_lines[1:],
            },
            "source_row": row_number,
        })
    return records


def fetch_page(year: int, page_title: str, api_url: str) -> tuple[str, str]:
    title = page_title.format(year=year)
    response = requests.get(
        api_url,
        params={
            "action": "parse",
            "page": title,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"Fandom API error: {payload['error']}")
    html = payload.get("parse", {}).get("text")
    if not html:
        raise RuntimeError("Fandom API response did not contain parsed page HTML")
    return html, f"https://hotwheels.fandom.com/wiki/{title}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--output", default=None)
    parser.add_argument("--page-title", default=DEFAULT_PAGE)
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--html-file", help="Optional saved Fandom page HTML; skips the network request")
    args = parser.parse_args()

    try:
        if args.html_file:
            html = Path(args.html_file).read_text(encoding="utf-8", errors="replace")
            source_url = f"https://hotwheels.fandom.com/wiki/{args.page_title.format(year=args.year)}"
        else:
            html, source_url = fetch_page(args.year, args.page_title, args.api_url)

        records = parse_table(html, args.year, source_url)
        if not records:
            raise RuntimeError("The Fandom table was found, but no valid Toy # rows were parsed")

        counts = {}
        for record in records:
            counts[record["toy_number"]] = counts.get(record["toy_number"], 0) + 1
        duplicate_skus = sorted(sku for sku, count in counts.items() if count > 1)

        result = {
            "schema_version": 1,
            "dataset": "hot-wheels-mainline",
            "year": args.year,
            "source": {
                "name": "Hot Wheels Wiki (Fandom)",
                "url": source_url,
                "api_url": args.api_url,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
            "record_count": len(records),
            "duplicate_toy_numbers": duplicate_skus,
            "records": records,
            "import_policy": {
                "toy_number": "candidate match key; duplicates must be reviewed",
                "collector_number": "grouping/reference only; never merge variants by this value",
                "source_annotations": "preserved verbatim as extracted lines",
                "catalog_write": "none; review snapshot only",
            },
        }
        output = Path(args.output or f"fandom-mainline-{args.year}.json")
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Imported rows: {len(records)}")
        print(f"Duplicate Toy # values: {len(duplicate_skus)}")
        print(f"Wrote review snapshot: {output}")
        return 0
    except Exception as exc:
        print(f"Fandom import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

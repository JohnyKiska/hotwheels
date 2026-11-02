#!/usr/bin/env python3
"""Import a Fandom yearly Mainline table into an isolated test catalog.

Default mode is a dry run: all database changes are rolled back. Writes require
--apply, HW_IMPORT_ALLOW_WRITE=1, and an explicit SQLite DATABASE_URL whose path
contains "test" or "sandbox".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import DATABASE_URL, SessionLocal  # noqa: E402
from app.mainline_importer import import_mainline_snapshot  # noqa: E402

DEFAULT_API = "https://hotwheels.fandom.com/api.php"
USER_AGENT = "HW-Catalog-Research/1.0 (read-only catalog importer)"
REQUIRED_HEADERS = ("toy #", "col.#", "model name", "series", "series #")


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _cell_lines(cell) -> list[str]:
    if cell is None:
        return []
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in cell.get_text("\n", strip=True).splitlines()
        if line.strip()
    ]


def parse_fandom_table(html: str, year: int) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    table = None
    indexes = {}
    for candidate in soup.find_all("table"):
        rows = candidate.find_all("tr")
        if not rows:
            continue
        headers = [
            _normalize_header(cell.get_text(" ", strip=True))
            for cell in rows[0].find_all(["th", "td"], recursive=False)
        ]
        if all(header in headers for header in REQUIRED_HEADERS):
            table = candidate
            indexes = {header: headers.index(header) for header in REQUIRED_HEADERS}
            break
    if table is None:
        raise ValueError("Could not find the yearly Mainline table with the required columns")

    records = []
    for row_number, row in enumerate(table.find_all("tr")[1:], start=2):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) <= max(indexes.values()):
            continue
        toy_lines = _cell_lines(cells[indexes["toy #"]])
        col_lines = _cell_lines(cells[indexes["col.#"]])
        model_lines = _cell_lines(cells[indexes["model name"]])
        series_lines = _cell_lines(cells[indexes["series"]])
        series_number_lines = _cell_lines(cells[indexes["series #"]])
        if not toy_lines or not model_lines:
            continue
        sku = toy_lines[0].upper()
        if not re.fullmatch(r"[A-Z0-9]{4,8}", sku):
            continue
        records.append({
            "toy_number": sku,
            "collector_number": col_lines[0] if col_lines else None,
            "model_name": model_lines[0],
            "series_name": series_lines[0] if series_lines else None,
            "series_number_raw": series_number_lines[0] if series_number_lines else None,
            "source_annotations": {
                "model": model_lines[1:],
                "series": series_lines[1:],
            },
            "source_row": row_number,
        })
    if not records:
        raise ValueError("The Mainline table was found, but no valid SKU rows were parsed")
    return {
        "schema_version": 1,
        "dataset": "hot-wheels-mainline",
        "year": year,
        "source": {
            "name": "Hot Wheels Wiki (Fandom)",
            "url": f"https://hotwheels.fandom.com/wiki/List_of_{year}_Hot_Wheels",
            "api_url": DEFAULT_API,
        },
        "record_count": len(records),
        "records": records,
    }


def fetch_snapshot(year: int, api_url: str) -> dict:
    page_title = f"List_of_{year}_Hot_Wheels"
    query = urlencode({
        "action": "parse",
        "page": page_title,
        "prop": "text",
        "format": "json",
        "formatversion": "2",
    })
    request = Request(
        f"{api_url}?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if "error" in payload:
        raise RuntimeError(f"Fandom API error: {payload['error']}")
    html = payload.get("parse", {}).get("text")
    if not html:
        raise RuntimeError("Fandom API response did not contain parsed page HTML")
    snapshot = parse_fandom_table(html, year)
    snapshot["source"]["api_url"] = api_url
    return snapshot


def _assert_safe_write_target() -> None:
    if os.environ.get("HW_IMPORT_ALLOW_WRITE") != "1":
        raise SystemExit("Refusing database write: set HW_IMPORT_ALLOW_WRITE=1 explicitly.")
    if "DATABASE_URL" not in os.environ:
        raise SystemExit("Refusing database write: set DATABASE_URL to the isolated test database.")
    url = DATABASE_URL.casefold()
    if not url.startswith("sqlite:"):
        raise SystemExit("Refusing database write: this seed importer currently permits SQLite test databases only.")
    if "test" not in url and "sandbox" not in url:
        raise SystemExit("Refusing database write: SQLite DATABASE_URL path must contain 'test' or 'sandbox'.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--html-file", help="Use a saved Fandom HTML page instead of fetching the API")
    parser.add_argument("--snapshot-json", help="Use an existing parsed Fandom snapshot JSON")
    parser.add_argument("--report-output", help="Optional path for a JSON import report")
    parser.add_argument("--apply", action="store_true", help="Commit into the explicitly configured isolated test DB")
    args = parser.parse_args()

    try:
        if args.apply:
            _assert_safe_write_target()

        if args.snapshot_json:
            snapshot = json.loads(Path(args.snapshot_json).read_text(encoding="utf-8"))
        elif args.html_file:
            html = Path(args.html_file).read_text(encoding="utf-8", errors="replace")
            snapshot = parse_fandom_table(html, args.year)
        else:
            snapshot = fetch_snapshot(args.year, args.api_url)

        if snapshot.get("year") != args.year:
            raise ValueError(f"Snapshot year {snapshot.get('year')!r} does not match --year {args.year}")

        with SessionLocal() as session:
            try:
                report = import_mainline_snapshot(session, snapshot)
                if args.apply:
                    session.commit()
                    report["database_action"] = "committed"
                else:
                    session.rollback()
                    report["database_action"] = "dry_run_rolled_back"
            except Exception:
                session.rollback()
                raise

        report["snapshot_record_count"] = len(snapshot.get("records", []))
        report["apply_requested"] = args.apply
        serialized = json.dumps(report, ensure_ascii=False, indent=2)
        print(serialized)
        if args.report_output:
            Path(args.report_output).write_text(serialized + "\n", encoding="utf-8")
        return 0
    except Exception as exc:
        print(f"Mainline import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

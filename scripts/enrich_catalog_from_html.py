#!/usr/bin/env python3
"""Build a reviewable enrichment preview from saved All Hot Wheels HTML pages.

This script is intentionally offline and non-destructive:
- It never edits collection.json.
- It matches pages to records by SKU (toyNum).
- It only writes a separate preview JSON file.
- Unmatched and ambiguous records are reported rather than guessed.

Usage:
  python -m pip install beautifulsoup4
  python scripts/enrich_catalog_from_html.py --html-dir saved_pages --output enrichment-preview.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from bs4 import BeautifulSoup

SKU_RE = re.compile(r"\bSKU\s+([A-Z0-9]{4,8})\b", re.I)
YEAR_RE = re.compile(r"\b(?:Release year|Year)\s*:?\s*(20\d{2})\b", re.I)
SCALE_RE = re.compile(r"\b(1\s*/\s*\d+)\b")
COLOR_LABELS = (
    "body color", "body source", "interior color", "interior source",
    "base color", "base premium", "base source", "window color", "window source",
    "detailed", "source", "premium", "color",
)
_FIELD_LABEL_PATTERN = "|".join(re.escape(label) for label in sorted(COLOR_LABELS, key=len, reverse=True))
FIELD_RE = re.compile(
    rf"(?P<label>{_FIELD_LABEL_PATTERN})\\s*:\\s*(?P<value>.*?)"
    rf"(?=\\s+(?:{_FIELD_LABEL_PATTERN})\\s*:|$)",
    re.I,
)


def section_text(soup: BeautifulSoup, heading_text: str) -> str | None:
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if heading.get_text(" ", strip=True).casefold() == heading_text.casefold():
            return heading.parent.get_text(" ", strip=True)
    return None


def parse_saved_page(path: Path) -> dict | None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.find("h1")
    name = title.get_text(" ", strip=True) if title else None
    canonical = soup.find("link", rel="canonical")
    source_url = canonical.get("href") if canonical else None

    # Use the page's model detail panel, not related-car cards, to find SKU.
    page_text = soup.get_text(" ", strip=True)
    sku_match = SKU_RE.search(page_text)
    if not sku_match:
        return None
    sku = sku_match.group(1).upper()

    year_match = YEAR_RE.search(page_text)
    scale_match = SCALE_RE.search(page_text)
    wheel_text = section_text(soup, "Wheels")
    color_text = section_text(soup, "Colors")

    wheel = None
    if wheel_text:
        wheel = re.sub(r"^\s*Wheels\s*", "", wheel_text, flags=re.I).strip() or None

    colors = []
    if color_text:
        text = re.sub(r"^\s*Colors\s*", "", color_text, flags=re.I).strip()
        for match in FIELD_RE.finditer(text):
            label = re.sub(r"\s+", " ", match.group(1)).strip().casefold()
            value = re.sub(r"\s+", " ", match.group(2)).strip()
            if value:
                colors.append({"label": label, "value": value})

    return {
        "sku": sku,
        "source_url": source_url,
        "source_file": path.name,
        "source_name": name,
        "release_year": int(year_match.group(1)) if year_match else None,
        "scale": scale_match.group(1).replace(" ", "") if scale_match else None,
        "wheel_description": wheel,
        "color_attributes": colors,
        "color_section_raw": color_text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="collection.json", help="Existing catalog JSON (read-only)")
    parser.add_argument("--html-dir", required=True, help="Directory with saved source HTML pages")
    parser.add_argument("--output", default="enrichment-preview.json", help="Preview output path")
    args = parser.parse_args()

    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    if not isinstance(catalog, list):
        raise SystemExit("Catalog must be a JSON array")

    by_sku: dict[str, list[dict]] = {}
    for record in catalog:
        sku = str(record.get("toyNum", "")).strip().upper()
        if sku:
            by_sku.setdefault(sku, []).append(record)

    parsed_pages = []
    for path in sorted(Path(args.html_dir).glob("*.html")):
        page = parse_saved_page(path)
        if page:
            parsed_pages.append(page)

    preview = []
    unmatched = []
    ambiguous = []
    for page in parsed_pages:
        matches = by_sku.get(page["sku"], [])
        if len(matches) == 1:
            record = matches[0]
            preview.append({
                "catalog_id": record.get("id"),
                "sku": page["sku"],
                "catalog_name": record.get("name"),
                "source_name": page["source_name"],
                "match": "sku_exact",
                "proposed_fields": {
                    "source_url": page["source_url"],
                    "release_year": page["release_year"],
                    "scale": page["scale"],
                    "wheel_description": page["wheel_description"],
                    "color_attributes": page["color_attributes"],
                },
                "source_file": page["source_file"],
                "color_section_raw": page["color_section_raw"],
            })
        elif len(matches) == 0:
            unmatched.append({"sku": page["sku"], "source_file": page["source_file"], "source_name": page["source_name"]})
        else:
            ambiguous.append({"sku": page["sku"], "source_file": page["source_file"], "record_count": len(matches)})

    result = {
        "mode": "preview_only",
        "catalog_file": str(Path(args.catalog)),
        "catalog_records": len(catalog),
        "html_pages_parsed": len(parsed_pages),
        "matched_pages": len(preview),
        "unmatched_pages": unmatched,
        "ambiguous_pages": ambiguous,
        "records": preview,
        "warning": "Review this file before merging. This script never modifies the source catalog and does not infer missing values."
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Parsed pages: {len(parsed_pages)}; matched: {len(preview)}; unmatched: {len(unmatched)}; ambiguous: {len(ambiguous)}")
    print(f"Wrote preview only: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

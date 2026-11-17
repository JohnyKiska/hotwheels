"""Offline Scrapling pilot for saved Hot Wheels Wiki/Fandom HTML pages."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any
from scrapling import Selector


def _text(node: Any) -> str:
    return " ".join(str(node.get_all_text(separator=" ", strip=True)).split())


def extract_page(path: Path, source_url: str | None = None) -> dict[str, Any]:
    page = Selector(path.read_text(encoding="utf-8", errors="replace"), url=source_url)
    title = page.css("title::text").get()
    headings = [{"level": n.tag, "text": _text(n)} for n in page.css("h1, h2, h3, h4") if _text(n)]
    tables = []
    for ti, table in enumerate(page.css("table"), 1):
        rows = []
        for ri, row in enumerate(table.css("tr"), 1):
            cells = row.css("th, td")
            if cells:
                rows.append({"row": ri, "cells": [
                    {"tag": c.tag, "text": _text(c), "html": c.get()} for c in cells
                ]})
        if rows:
            captions = table.css("caption")
            tables.append({"table": ti, "caption": _text(captions.first) if captions.first else None,
                           "rows": rows, "html": table.get()})
    links = [{"text": _text(a), "href": str(a.attrib["href"])}
             for a in page.css("a[href]")]
    images = []
    for img in page.css("img"):
        attrs = dict(img.attrib)
        src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-original")
        if src or attrs.get("srcset"):
            images.append({"src": src, "srcset": attrs.get("srcset"), "alt": attrs.get("alt"),
                           "title": attrs.get("title"), "all_attributes": attrs})
    canonical = page.css('link[rel="canonical"]::attr(href)').get()
    return {
        "source_file": str(path), "source_url": source_url or canonical,
        "page_title": str(title).strip() if title else None, "canonical_url": canonical,
        "headings": headings, "tables": tables, "links": links, "images": images,
        "counts": {"headings": len(headings), "tables": len(tables),
                   "links": len(links), "images": len(images)},
        "extraction_policy": "raw_source_values_only_no_catalog_mapping",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("html", nargs="+", type=Path, help="Saved HTML file(s)")
    p.add_argument("--output", type=Path, default=Path("scrapling-pilot.json"))
    p.add_argument("--url", help="Optional source URL")
    args = p.parse_args()
    missing = [str(f) for f in args.html if not f.is_file()]
    if missing:
        p.error("HTML file(s) not found: " + ", ".join(missing))
    reports = [extract_page(f, args.url) for f in args.html]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Parsed {len(reports)} page(s); report: {args.output}")
    for r in reports:
        c = r["counts"]
        print(f"- {r['source_file']}: {c['tables']} tables, {c['images']} images, {c['links']} links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline Scrapling pilot for saved Hot Wheels Wiki/Fandom HTML pages."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from scrapling import Selector


LAZY_IMAGE_ATTRIBUTES = (
    "data-src",
    "data-original",
    "data-lazy-src",
    "data-url",
)
GALLERY_SELECTORS = (
    ".wikia-gallery",
    ".gallery",
    ".gallerybox",
    ".thumb",
)
ARTICLE_SELECTORS = (
    "#mw-content-text .mw-parser-output",
    "#mw-content-text",
    "article",
    "body",
)


def _text(node: Any) -> str:
    return " ".join(str(node.get_all_text(separator=" ", strip=True)).split())


def _first_srcset(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.split(",", 1)[0].strip().split()
    return candidate[0] if candidate else None


def _resolved_url(value: str | None, base_url: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value or value.startswith(("data:", "javascript:")):
        return None
    return urljoin(base_url, value) if base_url else value


def _image_url(attrs: dict[str, str], base_url: str | None) -> tuple[str | None, str | None]:
    for name in LAZY_IMAGE_ATTRIBUTES:
        candidate = _resolved_url(attrs.get(name), base_url)
        if candidate:
            return candidate, name
    for name in ("data-srcset", "srcset"):
        candidate = _resolved_url(_first_srcset(attrs.get(name)), base_url)
        if candidate:
            return candidate, name
    candidate = _resolved_url(attrs.get("src"), base_url)
    return candidate, "src" if candidate else None


def _normalized_url_key(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def _positive_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _is_confident_ui_image(attrs: dict[str, str], url: str) -> bool:
    searchable = " ".join(
        str(attrs.get(key, "")) for key in ("alt", "title", "class", "id", "role")
    ).lower()
    path = urlsplit(url).path.lower()
    if any(token in searchable for token in ("avatar", "site-logo", "wiki-logo", "sprite", "placeholder")):
        return True
    if any(token in path for token in ("site-logo", "wiki-logo", "/sprites/", "placeholder")):
        return True
    if path.endswith((".gif", ".png")) and any(
        token in path for token in ("blank.", "spacer.", "loading.", "transparent.")
    ):
        return True
    # Deliberately do not reject images by pixel dimensions: small blister,
    # wheel and packaging photos can still be useful evidence.
    return False


def _parent_link(img: Any, base_url: str | None) -> str | None:
    # Scrapling's XPath support lets us retain the enclosing link without
    # depending on a browser or making a network request.
    try:
        href = img.xpath("ancestor::a[1]/@href").get()
    except (AttributeError, TypeError):
        href = None
    return _resolved_url(str(href), base_url) if href else None


def _image_identity(attrs: dict[str, str], parent_link: str | None, src: str) -> str:
    image_key = attrs.get("data-image-key")
    if image_key:
        return "data-image-key:" + image_key
    if parent_link:
        return "parent-link:" + _normalized_url_key(parent_link)
    return "thumbnail:" + _normalized_url_key(src)


def _collect_images(root: Any, base_url: str | None) -> tuple[list[dict[str, Any]], int]:
    role_nodes: list[tuple[str, Any]] = []
    for selector in GALLERY_SELECTORS:
        for container in root.css(selector):
            role_nodes.extend(("gallery", img) for img in container.css("img"))
    for table in root.css("table"):
        role_nodes.extend(("release_table", img) for img in table.css("img"))
    role_nodes.extend(("article", img) for img in root.css("img"))

    records: dict[str, dict[str, Any]] = {}
    skipped = 0
    for role, img in role_nodes:
        attrs = {str(k): str(v) for k, v in dict(img.attrib).items()}
        thumbnail_url, selected_from = _image_url(attrs, base_url)
        if not thumbnail_url:
            skipped += 1
            continue
        if _is_confident_ui_image(attrs, thumbnail_url):
            skipped += 1
            continue

        parent_link_url = _parent_link(img, base_url)
        identity = _image_identity(attrs, parent_link_url, thumbnail_url)
        if identity not in records:
            records[identity] = {
                # src is retained as a compatibility alias for earlier pilot reports.
                "src": thumbnail_url,
                "thumbnail_url": thumbnail_url,
                "selected_from": selected_from,
                "srcset": attrs.get("srcset"),
                "alt": attrs.get("alt"),
                "title": attrs.get("title"),
                "width": _positive_int(attrs.get("width")),
                "height": _positive_int(attrs.get("height")),
                "roles": [],
                "data_image_key": attrs.get("data-image-key"),
                "data_image_name": attrs.get("data-image-name"),
                "data_image_relevant": attrs.get("data-image-relevant"),
                "parent_link_url": parent_link_url,
                "all_attributes": attrs,
            }
        record = records[identity]
        if role not in record["roles"]:
            record["roles"].append(role)

        # Prefer the record that exposes a parent file link and preserve the
        # most informative thumbnail/lazy-load URL encountered.
        if parent_link_url and not record.get("parent_link_url"):
            record["parent_link_url"] = parent_link_url
        if selected_from in LAZY_IMAGE_ATTRIBUTES and record["selected_from"] == "src":
            record["src"] = thumbnail_url
            record["thumbnail_url"] = thumbnail_url
            record["selected_from"] = selected_from
            record["all_attributes"] = attrs
            record["alt"] = attrs.get("alt") or record["alt"]
            record["title"] = attrs.get("title") or record["title"]
            record["data_image_name"] = attrs.get("data-image-name") or record["data_image_name"]
            record["data_image_relevant"] = attrs.get("data-image-relevant") or record["data_image_relevant"]

    return list(records.values()), skipped


def extract_page(path: Path, source_url: str | None = None) -> dict[str, Any]:
    page = Selector(path.read_text(encoding="utf-8", errors="replace"), url=source_url)
    title = page.css("title::text").get()
    canonical = page.css('link[rel="canonical"]::attr(href)').get()
    base_url = source_url or canonical
    root = _article_root(page)

    headings = [
        {"level": n.tag, "text": _text(n)}
        for n in root.css("h1, h2, h3, h4")
        if _text(n)
    ]
    tables = []
    for ti, table in enumerate(root.css("table"), 1):
        rows = []
        for ri, row in enumerate(table.css("tr"), 1):
            cells = row.css("th, td")
            if cells:
                rows.append({
                    "row": ri,
                    "cells": [
                        {"tag": c.tag, "text": _text(c), "html": c.get()}
                        for c in cells
                    ],
                })
        if rows:
            captions = table.css("caption")
            tables.append({
                "table": ti,
                "caption": _text(captions.first) if captions.first else None,
                "rows": rows,
                "html": table.get(),
            })

    links = [
        {"text": _text(a), "href": str(a.attrib["href"])}
        for a in root.css("a[href]")
    ]
    images, skipped_images = _collect_images(root, base_url)
    return {
        "source_file": str(path),
        "source_url": source_url or canonical,
        "page_title": str(title).strip() if title else None,
        "canonical_url": canonical,
        "headings": headings,
        "tables": tables,
        "links": links,
        "images": images,
        "counts": {
            "headings": len(headings),
            "tables": len(tables),
            "links": len(links),
            "images": len(images),
            "images_skipped": skipped_images,
            "gallery_images": sum("gallery" in image["roles"] for image in images),
            "release_table_images": sum("release_table" in image["roles"] for image in images),
            "images_with_parent_link": sum(bool(image["parent_link_url"]) for image in images),
            "images_with_data_image_key": sum(bool(image["data_image_key"]) for image in images),
        },
        "extraction_policy": "raw_source_values_only_no_catalog_mapping",
        "image_policy": {
            "lazy_load_priority": list(LAZY_IMAGE_ATTRIBUTES),
            "identity_priority": ["data-image-key", "parent_link_url", "normalized_thumbnail_url"],
            "thumbnail_field": "thumbnail_url",
            "parent_link_field": "parent_link_url_exact_href_no_url_rewrite",
            "small_images": "retained_unless_confident_ui_asset",
            "scope": "article_content_only",
            "roles": ["gallery", "release_table", "article"],
        },
    }


def _article_root(page: Any) -> Any:
    for selector in ARTICLE_SELECTORS:
        matches = page.css(selector)
        if matches:
            return matches.first
    return page


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
    args.output.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Parsed {len(reports)} page(s); report: {args.output}")
    for report in reports:
        counts = report["counts"]
        print(
            f"- {report['source_file']}: {counts['tables']} tables, "
            f"{counts['images']} image records "
            f"({counts['gallery_images']} gallery, "
            f"{counts['release_table_images']} table), "
            f"{counts['images_with_parent_link']} with parent links, "
            f"{counts['images_skipped']} skipped, {counts['links']} links"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

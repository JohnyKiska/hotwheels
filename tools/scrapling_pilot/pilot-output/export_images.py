"""Download image evidence from a Scrapling v3 JSON report for manual review.

Uses only the URLs already present in the report. For Fandom File pages, it
attempts to discover the full-size image URL from the page HTML. If that fails,
it falls back to the captured thumbnail URL. No catalog or database writes.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen


USER_AGENT = "HW-Catalog-Scrapling-Pilot/1.0 (manual image review)"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".tif", ".tiff"}


def safe_name(value: str, limit: int = 90) -> str:
    value = unquote(str(value or "")).strip()
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._ ")
    return (value or "image")[:limit]


def guess_extension(url: str, content_type: str | None = None) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    content_type = (content_type or "").split(";", 1)[0].lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/avif": ".avif",
        "image/bmp": ".bmp",
        "image/tiff": ".tif",
    }.get(content_type, ".img")


def get_url(url: str, timeout: int = 30) -> tuple[bytes, str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
    with urlopen(request, timeout=timeout) as response:
        return response.read(), response.geturl(), response.headers.get("Content-Type", "")


class ImagePageParser(HTMLParser):
    """Collect likely full-resolution image URLs from a Fandom file page."""

    def __init__(self) -> None:
        super().__init__()
        self.candidates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "meta" and a.get("property") in {"og:image", "og:image:secure_url"} and a.get("content"):
            self.candidates.append(a["content"])
        if tag == "a" and a.get("class") and "fullImageLink" in a["class"].split() and a.get("href"):
            self.candidates.insert(0, a["href"])
        if tag == "img":
            cls = a.get("class", "")
            if "fullImage" in cls.split() and a.get("src"):
                self.candidates.insert(0, a["src"])


def resolve_image_url(parent_url: str | None, thumbnail_url: str | None) -> tuple[str | None, str]:
    """Resolve File-page hrefs to full image URLs; otherwise retain exact direct href."""
    if parent_url:
        path = urlsplit(parent_url).path.lower()
        is_file_page = "/wiki/file:" in path or "/wiki/file/" in path
        if not is_file_page:
            return parent_url, "parent_link_direct"
        try:
            html_bytes, final_url, content_type = get_url(parent_url)
            if "html" not in content_type.lower() and not html_bytes.lstrip().startswith((b"<!", b"<html", b"<HTML")):
                return final_url, "parent_link_response"
            parser = ImagePageParser()
            parser.feed(html_bytes.decode("utf-8", errors="replace"))
            for candidate in parser.candidates:
                absolute = urljoin(final_url, candidate)
                if urlsplit(absolute).scheme in {"http", "https"}:
                    return absolute, "file_page_full_image"
        except Exception as exc:
            if not thumbnail_url:
                return None, f"file_page_error:{type(exc).__name__}"
    if thumbnail_url:
        return thumbnail_url, "thumbnail_fallback"
    return None, "no_usable_url"


def image_records(report: list[dict]) -> list[tuple[str, dict]]:
    records: list[tuple[str, dict]] = []
    for page in report:
        title = page.get("page_title") or page.get("source_url") or "unknown_page"
        for image in page.get("images", []):
            records.append((str(title), image))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Path to scrapling-pilot-v3.json")
    parser.add_argument("--output-dir", type=Path, default=Path("photos"), help="Destination for per-model folders")
    parser.add_argument("--delay", type=float, default=0.25, help="Pause between image downloads in seconds")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"Input report not found: {args.input}")

    report = json.loads(args.input.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir.parent / "photo_manifest.csv"
    fields = [
        "page_title", "file_name", "status", "photo_type_manual", "quality_manual",
        "roles", "alt", "title", "data_image_name", "data_image_key",
        "thumbnail_url", "parent_link_url", "download_url", "url_source",
        "local_path", "content_type", "bytes", "error",
    ]

    total = 0
    ok = 0
    failed = 0
    with manifest_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()

        for page_title, image in image_records(report):
            total += 1
            folder = args.output_dir / safe_name(page_title)
            folder.mkdir(parents=True, exist_ok=True)

            key_or_name = image.get("data_image_name") or image.get("data_image_key") or image.get("alt") or "image"
            stem = f"{total:03d}_{safe_name(key_or_name)}"
            thumbnail = image.get("thumbnail_url") or image.get("src")
            parent = image.get("parent_link_url")
            download_url, url_source = resolve_image_url(parent, thumbnail)
            row = {
                "page_title": page_title,
                "file_name": "",
                "status": "failed",
                "photo_type_manual": "",
                "quality_manual": "",
                "roles": ";".join(image.get("roles") or []),
                "alt": image.get("alt") or "",
                "title": image.get("title") or "",
                "data_image_name": image.get("data_image_name") or "",
                "data_image_key": image.get("data_image_key") or "",
                "thumbnail_url": thumbnail or "",
                "parent_link_url": parent or "",
                "download_url": download_url or "",
                "url_source": url_source,
                "local_path": "",
                "content_type": "",
                "bytes": 0,
                "error": "",
            }

            if not download_url:
                row["error"] = "No usable image URL"
                failed += 1
                writer.writerow(row)
                continue

            try:
                data, final_url, content_type = get_url(download_url, timeout=args.timeout)
                if not data:
                    raise ValueError("Empty response")
                extension = guess_extension(final_url, content_type)
                destination = folder / (stem + extension)
                destination.write_bytes(data)
                row.update({
                    "file_name": destination.name,
                    "status": "downloaded",
                    "download_url": final_url,
                    "local_path": str(destination.resolve()),
                    "content_type": content_type,
                    "bytes": len(data),
                })
                ok += 1
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                failed += 1
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                failed += 1

            writer.writerow(row)
            if args.delay > 0:
                time.sleep(args.delay)

            if total % 20 == 0:
                print(f"Processed {total} images: {ok} downloaded, {failed} failed")

    print(f"Finished: {total} records, {ok} downloaded, {failed} failed")
    print(f"Photo folders: {args.output_dir.resolve()}")
    print(f"Manifest: {manifest_path.resolve()}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

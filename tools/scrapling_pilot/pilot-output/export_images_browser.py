"""Export Scrapling v3 image evidence through a visible Chrome session.

This uses a dedicated persistent Playwright Chrome profile so the user can
complete any Cloudflare check manually. It does not solve, evade, or automate
CAPTCHA/challenge mechanisms. No catalog/database writes are performed.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.sync_api import Page, sync_playwright


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".tif", ".tiff"}
IMAGE_FETCH_JS = r"""
async () => {
    const img = document.querySelector("img");
    if (!img) throw new Error("Browser did not render an image element");
    if (!img.complete || img.naturalWidth === 0) {
        await new Promise((resolve, reject) => {
            img.addEventListener("load", resolve, { once: true });
            img.addEventListener("error", () => reject(new Error("Image failed to load")), { once: true });
            setTimeout(() => reject(new Error("Timed out waiting for image load")), 20000);
        });
    }
    const imageUrl = img.currentSrc || img.src;
    const response = await fetch(imageUrl, { credentials: "include" });
    if (!response.ok) throw new Error("Image fetch returned HTTP " + response.status);
    const blob = await response.blob();
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let binary = "";
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    return {
        base64: btoa(binary),
        content_type: blob.type || response.headers.get("content-type") || "",
        image_url: imageUrl,
        width: img.naturalWidth,
        height: img.naturalHeight
    };
}
"""


def safe_name(value: str, limit: int = 100) -> str:
    value = unquote(str(value or "")).strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._ ")
    return (value or "image")[:limit]


def guess_extension(url: str, content_type: str = "") -> str:
    path = urlsplit(url).path.lower()
    match = re.search(r"\.(jpe?g|png|gif|webp|bmp|avif|tiff?)((?:/)|$)", path)
    if match:
        ext = match.group(1)
        return ".jpg" if ext == "jpeg" else f".{ext}"
    mime = content_type.split(";", 1)[0].lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/avif": ".avif",
        "image/bmp": ".bmp",
        "image/tiff": ".tif",
    }.get(mime, ".img")


def is_cloudflare_challenge(page: Page) -> bool:
    try:
        title = (page.title() or "").lower()
        body = (page.locator("body").inner_text(timeout=2500) or "")[:5000].lower()
        markers = (
            "just a moment",
            "checking your browser",
            "verify you are human",
            "performing security verification",
            "cf-chl-",
        )
        return any(marker in title or marker in body for marker in markers)
    except Exception:
        return False


def wait_for_manual_challenge(page: Page, label: str) -> None:
    if not is_cloudflare_challenge(page):
        return
    print()
    print(f"Cloudflare проверка обнаружена: {label}")
    print("Пройди проверку вручную в открытом окне Chrome.")
    input("Когда проверка завершится и страница откроется, нажми Enter здесь...")
    page.wait_for_timeout(2500)
    if is_cloudflare_challenge(page):
        raise RuntimeError("Cloudflare challenge is still present; no automated bypass was attempted")


def navigate(page: Page, url: str, timeout_ms: int) -> None:
    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    challenge_was_present = is_cloudflare_challenge(page)
    wait_for_manual_challenge(page, url)
    if response is not None and response.status >= 400:
        # Cloudflare can return an initial 403 challenge response. If the user
        # has just completed that challenge, do not treat the original status
        # as the final result; the subsequent DOM/image check is authoritative.
        if not challenge_was_present and not is_cloudflare_challenge(page):
            raise RuntimeError(f"HTTP {response.status} while opening {url}")
    page.wait_for_timeout(350)


def resolve_full_image_url(page: Page, parent_url: str, timeout_ms: int) -> tuple[str, str]:
    path = urlsplit(parent_url).path.lower()
    if "/wiki/file:" not in path and "/wiki/file/" not in path:
        return parent_url, "parent_link_direct"

    navigate(page, parent_url, timeout_ms)
    candidate = page.evaluate("""() => {
        const selectors = [
            "a.fullImageLink[href]",
            ".fullImageLink a[href]",
            "#file a[href]",
            "a.image[href]"
        ];
        const found = [];
        for (const selector of selectors) {
            for (const node of document.querySelectorAll(selector)) {
                if (node.href) found.push(node.href);
            }
        }
        const og = document.querySelector('meta[property="og:image"]');
        if (og?.content) found.push(og.content);
        const isImage = (value) => /\\.(jpe?g|png|gif|webp|bmp|avif|tiff?)(?:\\/|$)/i.test(new URL(value).pathname);
        return found.find(value => isImage(value) && /static\\.wikia\\.nocookie\\.net/i.test(value))
            || found.find(value => isImage(value))
            || found[0]
            || null;
    }""")
    if candidate:
        return candidate, "file_page_browser_dom"
    raise RuntimeError("Could not find an image link on the Fandom File page")


def fetch_image_bytes(page: Page, image_url: str, timeout_ms: int) -> tuple[bytes, str, str, int, int]:
    navigate(page, image_url, timeout_ms)
    wait_for_manual_challenge(page, image_url)
    result = page.evaluate(IMAGE_FETCH_JS)
    data = base64.b64decode(result["base64"])
    if not data:
        raise RuntimeError("Empty image response")
    return (
        data,
        result.get("content_type", ""),
        result.get("image_url", image_url),
        int(result.get("width", 0)),
        int(result.get("height", 0)),
    )


def image_records(report: list[dict]) -> list[tuple[str, dict]]:
    records: list[tuple[str, dict]] = []
    for page in report:
        title = page.get("page_title") or page.get("source_url") or "unknown_page"
        for image in page.get("images", []):
            records.append((str(title), image))
    return records


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=script_dir / "scrapling-pilot-v3.json")
    parser.add_argument("--output-dir", type=Path, default=script_dir / "photos")
    parser.add_argument("--profile-dir", type=Path, default=script_dir / "chrome-test-profile")
    parser.add_argument("--limit", type=int, default=5, help="Images to process; use 0 for all records")
    parser.add_argument("--delay", type=float, default=0.8, help="Pause between images in seconds")
    parser.add_argument("--timeout", type=int, default=60000, help="Navigation timeout in milliseconds")
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"Input report not found: {args.input}")
    if args.limit < 0:
        parser.error("--limit must be 0 or a positive integer")

    report = json.loads(args.input.read_text(encoding="utf-8"))
    records = image_records(report)
    if args.limit:
        records = records[:args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.profile_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir.parent / "photo_manifest_browser.csv"
    fields = [
        "page_title", "file_name", "status", "photo_type_manual", "quality_manual",
        "roles", "alt", "title", "data_image_name", "data_image_key",
        "thumbnail_url", "parent_link_url", "download_url", "url_source",
        "local_path", "content_type", "bytes", "width", "height", "error",
    ]

    total = downloaded = skipped = failed = 0
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(args.profile_dir.resolve()),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_navigation_timeout(args.timeout)

        try:
            with manifest_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=fields)
                writer.writeheader()

                for index, (page_title, image) in enumerate(records, start=1):
                    total += 1
                    folder = args.output_dir / safe_name(page_title)
                    folder.mkdir(parents=True, exist_ok=True)

                    key_or_name = (
                        image.get("data_image_name")
                        or image.get("data_image_key")
                        or image.get("alt")
                        or "image"
                    )
                    stem = f"{index:03d}_{safe_name(key_or_name)}"
                    existing = next(folder.glob(stem + ".*"), None)
                    thumbnail = image.get("thumbnail_url") or image.get("src") or ""
                    parent = image.get("parent_link_url") or ""
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
                        "thumbnail_url": thumbnail,
                        "parent_link_url": parent,
                        "download_url": "",
                        "url_source": "",
                        "local_path": "",
                        "content_type": "",
                        "bytes": 0,
                        "width": 0,
                        "height": 0,
                        "error": "",
                    }

                    if existing and existing.stat().st_size > 0:
                        row.update({
                            "file_name": existing.name,
                            "status": "skipped_existing",
                            "local_path": str(existing.resolve()),
                            "bytes": existing.stat().st_size,
                        })
                        skipped += 1
                        writer.writerow(row)
                        continue

                    try:
                        if parent:
                            image_url, url_source = resolve_full_image_url(page, parent, args.timeout)
                        elif thumbnail:
                            image_url, url_source = thumbnail, "thumbnail_fallback"
                        else:
                            raise RuntimeError("No usable parent or thumbnail URL")

                        try:
                            data, content_type, final_url, width, height = fetch_image_bytes(
                                page, image_url, args.timeout
                            )
                        except Exception as first_error:
                            if thumbnail and thumbnail != image_url:
                                print(f"[{index}/{total}] Original failed, trying thumbnail: {first_error}")
                                image_url, url_source = thumbnail, "thumbnail_fallback_after_error"
                                data, content_type, final_url, width, height = fetch_image_bytes(
                                    page, image_url, args.timeout
                                )
                            else:
                                raise

                        extension = guess_extension(final_url, content_type)
                        destination = folder / (stem + extension)
                        destination.write_bytes(data)
                        row.update({
                            "file_name": destination.name,
                            "status": "downloaded",
                            "download_url": final_url,
                            "url_source": url_source,
                            "local_path": str(destination.resolve()),
                            "content_type": content_type,
                            "bytes": len(data),
                            "width": width,
                            "height": height,
                        })
                        downloaded += 1
                        print(f"[{index}/{len(records)}] OK {destination.name} ({width}x{height}, {len(data)} bytes)")
                    except Exception as exc:
                        row["error"] = f"{type(exc).__name__}: {exc}"
                        failed += 1
                        print(f"[{index}/{len(records)}] FAILED {row['data_image_name'] or stem}: {row['error']}")

                    writer.writerow(row)
                    csv_file.flush()
                    if args.delay > 0:
                        time.sleep(args.delay)
        finally:
            context.close()

    print()
    print(f"Finished: {total} processed, {downloaded} downloaded, {skipped} already present, {failed} failed")
    print(f"Photo folders: {args.output_dir.resolve()}")
    print(f"Manifest: {manifest_path.resolve()}")
    print(f"Chrome profile: {args.profile_dir.resolve()}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

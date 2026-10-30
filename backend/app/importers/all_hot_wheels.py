"""Read-only parser for individual All Hot Wheels model pages.

The parser extracts only fields visibly labelled or structurally identified on
the saved page. Source terminology (especially special labels such as "chase")
is preserved verbatim and is never normalized to TH/STH.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any


_YEAR_MIN = 1968
_YEAR_MAX = 2100
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str | None] | None = None) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[_Node | str] = []

    def text(self) -> str:
        return " ".join(part for child in self.children
                        for part in ([child] if isinstance(child, str) else [child.text()]) if part).strip()

    def descendants(self, tag: str | None = None):
        for child in self.children:
            if isinstance(child, _Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.descendants(tag)

    def child_nodes(self, tag: str | None = None) -> list["_Node"]:
        return [child for child in self.children if isinstance(child, _Node)
                and (tag is None or child.tag == tag)]


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(_Node(tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if not self.skip_depth and data.strip():
            self.stack[-1].children.append(data)


def _clean(value: str | None) -> str:
    return re.sub(r"\\s+", " ", value or "").strip()


def _fraction(value: str) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"\\s*(\\d+)\\s*/\\s*(\\d+)\\s*", value)
    if not match:
        return None, None
    index, total = int(match.group(1)), int(match.group(2))
    if index < 1 or total < 1 or index > total:
        return None, None
    return index, total


def _label_values(root: _Node) -> dict[str, str]:
    values: dict[str, str] = {}
    known = {"SKU", "Release year", "Scale", "Base material", "Series index", "Mainline #"}
    for node in root.descendants("div"):
        children = node.child_nodes("div")
        if len(children) < 2:
            continue
        label = _clean(children[0].text()).rstrip(":")
        if label in known:
            values[label] = _clean(children[1].text())
    return values


def _canonical_url(root: _Node) -> str | None:
    for node in root.descendants("link"):
        if node.attrs.get("rel") == "canonical" and node.attrs.get("href"):
            return node.attrs["href"]
    return None


def _meta_content(root: _Node, name: str) -> str | None:
    for node in root.descendants("meta"):
        if node.attrs.get("name") == name and node.attrs.get("content"):
            return node.attrs["content"]
    return None


def _section_after_heading(root: _Node, heading: str) -> _Node | None:
    for parent in root.descendants():
        children = parent.children
        for index, child in enumerate(children):
            if isinstance(child, _Node) and child.tag in {"h2", "h3"} and _clean(child.text()).casefold() == heading.casefold():
                for following in children[index + 1:]:
                    if isinstance(following, _Node):
                        return following
    return None


def _extract_wheels(section: _Node | None) -> list[dict[str, str]]:
    wheels: list[dict[str, str]] = []
    if section is None:
        return wheels
    for badge in section.descendants("span"):
        code_node = next((node for node in badge.descendants("span")
                          if "font-mono" in (node.attrs.get("class") or "")), None)
        if code_node:
            code = _clean(code_node.text())
            name = _clean(_clean(badge.text()).replace(code, "", 1))
            if code and name:
                wheels.append({"code": code, "name": name})
    return wheels


def _extract_tags(section: _Node | None) -> list[str]:
    if section is None:
        return []
    tags = []
    for link in section.descendants("a"):
        value = _clean(link.text())
        if value and value not in tags:
            tags.append(value)
    return tags


def _extract_colors(section: _Node | None) -> list[dict[str, str]]:
    if section is None:
        return []
    colors: list[dict[str, str]] = []
    for chip in section.descendants("div"):
        spans = [span for span in chip.child_nodes("span") if _clean(span.text())]
        if len(spans) >= 2:
            label = _clean(spans[0].text()).rstrip(":").strip().casefold()
            value = _clean(spans[-1].text())
            if label in {"color", "detailed", "source", "premium"} and value:
                parent_text = _clean(chip.text())
                if parent_text and len(parent_text) < 100:
                    colors.append({"attribute": label, "value": value})
    return colors


def preview_all_hot_wheels_html(text: str, expected_year: int | None = None) -> dict[str, Any]:
    """Parse one saved All Hot Wheels car detail page into a read-only candidate."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Прикрепи HTML-страницу карточки All Hot Wheels перед предпросмотром.")
    if expected_year is not None and (
        not isinstance(expected_year, int) or isinstance(expected_year, bool)
        or not _YEAR_MIN <= expected_year <= _YEAR_MAX
    ):
        raise ValueError(f"Год каталога должен быть в диапазоне {_YEAR_MIN}–{_YEAR_MAX}.")

    parser = _PageParser()
    parser.feed(text)
    root = parser.root
    title_node = next(root.descendants("title"), None)
    title = _clean(title_node.text()) if title_node else ""
    h1 = next(root.descendants("h1"), None)
    name = _clean(h1.text()) if h1 else ""
    if not name:
        raise ValueError("Не найден заголовок модели (h1). Это не похоже на карточку All Hot Wheels.")

    fields = _label_values(root)
    toy_number = fields.get("SKU")
    if not toy_number or not re.fullmatch(r"[A-Za-z0-9]{5}", toy_number):
        raise ValueError("На странице не найден корректный Toy Number в поле SKU.")

    year_text = fields.get("Release year")
    year_match = re.fullmatch(r"\\d{4}", year_text or "")
    if not year_match:
        raise ValueError("На странице не найден корректный Release year.")
    release_year = int(year_text)
    if not _YEAR_MIN <= release_year <= _YEAR_MAX:
        raise ValueError("Release year на странице вне допустимого диапазона.")
    if expected_year is not None and release_year != expected_year:
        raise ValueError(f"Страница относится к {release_year} году, а выбран год {expected_year}.")

    canonical = _canonical_url(root)
    category_slug = None
    if canonical:
        match = re.search(r"/car/\\d{4}/([^/]+)/", canonical)
        category_slug = match.group(1) if match else None

    category = {
        "mainline": "Mainline",
        "fast-furious": "Fast & Furious",
        "character-cars": "Character Cars",
        "themed-entertainment": "Themed Entertainment",
    }.get(category_slug, category_slug.replace("-", " ").title() if category_slug else None)

    # The detail page prints a compact "Category · Series · #x/y" line.
    # Prefer it over decorative badges elsewhere in the site navigation.
    category_series_line = None
    for paragraph in root.descendants("p"):
        paragraph_text = _clean(paragraph.text())
        match = re.fullmatch(r"(.+?)\\s*[·•]\\s*(.+?)\\s*[·•]\\s*#\\s*(\\d+\\s*/\\s*\\d+)", paragraph_text)
        if match:
            category_series_line = (match.group(1).strip(), match.group(2).strip(), match.group(3))
            break
    if category_series_line:
        category, summary_series_name, summary_fraction = category_series_line
    else:
        summary_series_name, summary_fraction = None, None

    # The first primary badge beside the model heading carries the source's own
    # special-label wording. Do not translate "chase" into TH/STH.
    special_label = None
    for badge in root.descendants("span"):
        badge_text = _clean(badge.text())
        classes = badge.attrs.get("class") or ""
        if "bg-primary" in classes and badge_text:
            special_label = badge_text
            break

    series_badges = [
        _clean(node.text())
        for node in root.descendants("span")
        if "bg-brand-indigo" in (node.attrs.get("class") or "")
        and _clean(node.text())
        and _clean(node.text()).casefold() not in {"a", "all hot wheels"}
    ]
    series_name = summary_series_name or (max(series_badges, key=len) if series_badges else None)

    series_index, series_total = _fraction(fields.get("Series index", ""))
    if series_index is None and summary_fraction:
        series_index, series_total = _fraction(summary_fraction)
    mainline_number_text = fields.get("Mainline #", "")
    mainline_number = int(mainline_number_text) if mainline_number_text.isdigit() else None

    wheels = _extract_wheels(_section_after_heading(root, "Wheels"))
    colors = _extract_colors(_section_after_heading(root, "Colors"))
    tags = _extract_tags(_section_after_heading(root, "Tags"))

    source_fields = {
        "toy_number": "SKU",
        "name": "h1",
        "release_year": "Release year",
        "scale": "Scale",
        "base_material": "Base material",
        "series_name": "category/series summary or series badge",
        "series_index": "Series index",
        "mainline_number": "Mainline #",
        "special_label": "primary badge",
        "wheels": "Wheels",
        "colors": "Colors",
        "tags": "Tags",
        "category": "canonical URL category segment",
    }
    record = {
        "toy_number": toy_number,
        "name": name,
        "release_year": release_year,
        "category": category,
        "category_slug": category_slug,
        "special_label": special_label,
        "scale": fields.get("Scale"),
        "base_material": fields.get("Base material"),
        "series_name": series_name,
        "series_index": series_index,
        "series_total": series_total,
        "mainline_number": mainline_number,
        "wheels": wheels,
        "colors": colors,
        "tags": tags,
        "source_url": canonical,
        "source_fields": source_fields,
        "raw_title": title or None,
        "review_status": "candidate",
    }
    return {
        "importer": "all_hot_wheels",
        "mode": "preview_only",
        "writes_to_catalog": False,
        "source_format": "all_hot_wheels_car_html",
        "records": [record],
        "issues": [],
        "summary": {"records_found": 1, "errors": 0, "warnings": 0, "ready_for_review": True},
    }

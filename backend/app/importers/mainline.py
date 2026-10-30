"""Safe preview parser for pasted Hot Wheels Mainline checklist rows.

This module deliberately does not write to the catalog database. It turns the
legacy converter's tab-separated clipboard format into reviewable candidates.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from collections import defaultdict
from typing import Any

_TOY_NUMBER_RE = re.compile(r"^[A-Za-z0-9]{5}$")
_FRACTION_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_YEAR_MIN = 1968
_YEAR_MAX = 2100


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _parse_fraction(value: str) -> tuple[int | None, int | None]:
    match = _FRACTION_RE.search(value)
    if not match:
        return None, None
    index, total = int(match.group(1)), int(match.group(2))
    if index < 1 or total < 1 or index > total:
        return None, None
    return index, total


def preview_mainline_tsv(text: str, catalog_year: int) -> dict[str, Any]:
    """Parse legacy converter TSV into candidates, warnings, and summary.

    Expected row shape is: toy number, assortment/catalog number, model name,
    optional series. Continuation lines may contain series fractions, Treasure
    Hunt/Exclusive markers, or other notes, matching converter.html behavior.
    Duplicate rows are reported but never merged or discarded.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Вставь текст чек-листа перед предпросмотром.")
    if not isinstance(catalog_year, int) or isinstance(catalog_year, bool):
        raise ValueError("Год каталога должен быть целым числом.")
    if not _YEAR_MIN <= catalog_year <= _YEAR_MAX:
        raise ValueError(f"Год каталога должен быть в диапазоне {_YEAR_MIN}–{_YEAR_MAX}.")

    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    records: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finish_record() -> None:
        if current is not None:
            records.append(current)

    for line_number, line in enumerate(lines, start=1):
        cells = [_clean(cell) for cell in line.split("\t")]
        first = cells[0] if cells else ""

        if first.casefold() in {"toy #", "toy number", "toy no."}:
            continue

        if len(cells) >= 3 and _TOY_NUMBER_RE.fullmatch(first):
            finish_record()
            series_index, series_total = _parse_fraction(line)
            current = {
                "source_row": line_number,
                "toy_number": first,
                "assortment_number": cells[1] or None,
                "name": cells[2],
                "catalog_year": catalog_year,
                "series_name": cells[3] if len(cells) > 3 and cells[3] else None,
                "series_index": series_index,
                "series_total": series_total,
                "rarity": "Mainline",
                "notes": [],
                "raw_lines": [line],
                "review_status": "candidate",
            }
            if not cells[2]:
                issues.append({
                    "row": line_number,
                    "severity": "error",
                    "code": "missing_name",
                    "message": f"У строки {line_number} нет названия модели.",
                    "toy_number": first,
                })
            if series_index is None and _FRACTION_RE.search(line):
                issues.append({
                    "row": line_number,
                    "severity": "warning",
                    "code": "invalid_series_fraction",
                    "message": f"Не удалось проверить номер в серии в строке {line_number}.",
                    "toy_number": first,
                })
            continue

        if current is None:
            if len(cells) > 1 and any(cells):
                issues.append({
                    "row": line_number,
                    "severity": "warning",
                    "code": "unrecognized_line",
                    "message": f"Строка {line_number} не похожа на строку машинки и пропущена.",
                })
            continue

        current["raw_lines"].append(line)
        fraction = _FRACTION_RE.search(line)
        if fraction:
            index, total = _parse_fraction(line)
            if index is not None:
                current["series_index"] = index
                current["series_total"] = total
        lower_line = line.casefold()
        if "treasure hunt" in lower_line or re.search(r"\bth\b", lower_line):
            current["rarity"] = "Treasure Hunt (TH)"
        elif "exclusive" in lower_line:
            current["rarity"] = "Exclusive"
        note = _clean(_FRACTION_RE.sub("", line))
        if note and note.casefold() not in {"new for", "excl"}:
            current["notes"].append(note)

    finish_record()

    if not records:
        issues.append({
            "row": None,
            "severity": "error",
            "code": "no_records",
            "message": "Не найдены строки машинок. Ожидаются строки TSV с Toy №, номером каталога и названием.",
        })

    by_toy_number: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_toy_number[record["toy_number"].casefold()].append(record)
    for duplicates in by_toy_number.values():
        if len(duplicates) < 2:
            continue
        names = {item["name"].casefold() for item in duplicates}
        first_record = duplicates[0]
        issues.append({
            "row": first_record["source_row"],
            "severity": "warning",
            "code": "duplicate_toy_number",
            "message": (
                f"Toy № {first_record['toy_number']} встречается {len(duplicates)} раз. "
                "Строки сохранены отдельно для ручной проверки."
            ),
            "toy_number": first_record["toy_number"],
            "rows": [item["source_row"] for item in duplicates],
            "different_names": len(names) > 1,
        })

    for record in records:
        record["notes"] = list(dict.fromkeys(record["notes"]))
        record["raw_text"] = "\n".join(record.pop("raw_lines"))

    error_count = sum(issue["severity"] == "error" for issue in issues)
    warning_count = sum(issue["severity"] == "warning" for issue in issues)
    return {
        "importer": "mainline",
        "mode": "preview_only",
        "writes_to_catalog": False,
        "catalog_year": catalog_year,
        "records": records,
        "issues": issues,
        "summary": {
            "records_found": len(records),
            "errors": error_count,
            "warnings": warning_count,
            "ready_for_review": error_count == 0,
        },
    }


class _FandomListParser(HTMLParser):
    """Extract the primary sortable wikitable without interpreting page chrome."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.target_table_depth: int | None = None
        self.rows: list[list[str]] = []
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None
        self.title_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "table":
            self.table_depth += 1
            classes = set((attributes.get("class") or "").split())
            if self.target_table_depth is None and {"sortable", "wikitable"}.issubset(classes):
                self.target_table_depth = self.table_depth
        elif self.target_table_depth == self.table_depth:
            if tag == "tr":
                self.current_row = []
            elif tag in {"th", "td"} and self.current_row is not None:
                self.current_cell = []
            elif tag == "br" and self.current_cell is not None:
                self.current_cell.append(" ")
            elif tag == "img" and self.current_cell is not None:
                alt = attributes.get("alt")
                if alt:
                    self.current_cell.append(alt)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if self.target_table_depth == self.table_depth:
            if tag in {"th", "td"} and self.current_cell is not None:
                self.current_row.append(_clean("".join(self.current_cell)))
                self.current_cell = None
            elif tag == "tr" and self.current_row is not None:
                if any(self.current_row):
                    self.rows.append(self.current_row)
                self.current_row = None
        if tag == "table":
            if self.target_table_depth == self.table_depth:
                self.target_table_depth = None
            self.table_depth = max(0, self.table_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.current_cell is not None and self.target_table_depth == self.table_depth:
            self.current_cell.append(data)


def preview_mainline_fandom_html(text: str, catalog_year: int) -> dict[str, Any]:
    """Preview the main sortable table from a Fandom yearly Hot Wheels list.

    Fandom's Col.# is a collector number, not an assortment number. The parser
    keeps it in a separate field and never writes to the catalog database.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Прикрепи HTML-страницу списка перед предпросмотром.")
    if not isinstance(catalog_year, int) or isinstance(catalog_year, bool):
        raise ValueError("Год каталога должен быть целым числом.")
    if not _YEAR_MIN <= catalog_year <= _YEAR_MAX:
        raise ValueError(f"Год каталога должен быть в диапазоне {_YEAR_MIN}–{_YEAR_MAX}.")

    parser = _FandomListParser()
    parser.feed(text)
    title = _clean("".join(parser.title_parts))
    title_year = re.search(r"List of\s+(\d{4})\s+Hot Wheels", title, re.IGNORECASE)
    if title_year and int(title_year.group(1)) != catalog_year:
        raise ValueError(
            f"Страница относится к {title_year.group(1)} году, а выбран год {catalog_year}."
        )

    if not parser.rows:
        raise ValueError(
            "Не найдена основная таблица Fandom (sortable wikitable). "
            "Для страниц отдельных моделей используй другой источник."
        )

    headers = [cell.casefold().replace(" ", "") for cell in parser.rows[0]]
    required_headers = {"toy#", "col.#", "modelname", "series", "series#"}
    if not required_headers.issubset(set(headers)):
        raise ValueError("Таблица Fandom не содержит ожидаемые колонки Toy #, Col.#, Model Name, Series и Series #.")

    column_indexes = {header: index for index, header in enumerate(headers)}
    records: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for source_row, cells in enumerate(parser.rows[1:], start=2):
        if len(cells) <= max(column_indexes[h] for h in required_headers):
            issues.append({
                "row": source_row,
                "severity": "warning",
                "code": "incomplete_table_row",
                "message": f"Строка таблицы {source_row} не содержит все обязательные колонки.",
            })
            continue

        toy_number = cells[column_indexes["toy#"]].strip()
        collector_number = cells[column_indexes["col.#"]].strip()
        name = cells[column_indexes["modelname"]].strip()
        series_cell = cells[column_indexes["series"]].strip()
        series_fraction = cells[column_indexes["series#"]].strip()

        if not _TOY_NUMBER_RE.fullmatch(toy_number):
            issues.append({
                "row": source_row,
                "severity": "warning",
                "code": "invalid_toy_number",
                "message": f"В строке таблицы {source_row} код Toy # не распознан.",
                "toy_number": toy_number or None,
            })
            continue
        if not name:
            issues.append({
                "row": source_row,
                "severity": "error",
                "code": "missing_name",
                "message": f"У строки таблицы {source_row} нет названия модели.",
                "toy_number": toy_number,
            })

        series_index, series_total = _parse_fraction(series_fraction)
        if series_fraction and series_index is None:
            issues.append({
                "row": source_row,
                "severity": "warning",
                "code": "invalid_series_fraction",
                "message": f"Не удалось проверить номер серии в строке таблицы {source_row}.",
                "toy_number": toy_number,
            })

        lowered_series = series_cell.casefold()
        if "super treasure hunt" in lowered_series:
            rarity = "Super Treasure Hunt (STH)"
        elif "treasure hunt" in lowered_series:
            rarity = "Treasure Hunt (TH)"
        else:
            rarity = "Mainline"

        clean_series = re.sub(r"\b(?:super\s+)?treasure\s+hunt\b", "", series_cell, flags=re.IGNORECASE)
        clean_series = re.sub(r"\bnew\s+for\s+\d{4}!?", "", clean_series, flags=re.IGNORECASE)
        clean_series = _clean(clean_series).strip(" -–|")

        notes = []
        new_for = re.search(r"New for\s+(\d{4})!?", series_cell, re.IGNORECASE)
        if new_for:
            notes.append(f"New for {new_for.group(1)}")
        if rarity != "Mainline":
            notes.append(rarity)

        records.append({
            "source_row": source_row,
            "toy_number": toy_number,
            "collector_number": collector_number or None,
            "assortment_number": None,
            "name": name,
            "catalog_year": catalog_year,
            "series_name": clean_series or None,
            "series_index": series_index,
            "series_total": series_total,
            "rarity": rarity,
            "notes": notes,
            "raw_text": "\t".join(cells),
            "review_status": "candidate",
        })

    by_toy_number: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_toy_number[record["toy_number"].casefold()].append(record)
    for duplicates in by_toy_number.values():
        if len(duplicates) < 2:
            continue
        first_record = duplicates[0]
        issues.append({
            "row": first_record["source_row"],
            "severity": "warning",
            "code": "duplicate_toy_number",
            "message": (
                f"Toy № {first_record['toy_number']} встречается {len(duplicates)} раз. "
                "Строки сохранены отдельно для ручной проверки."
            ),
            "toy_number": first_record["toy_number"],
            "rows": [item["source_row"] for item in duplicates],
            "different_names": len({item["name"].casefold() for item in duplicates}) > 1,
        })

    if not records:
        issues.append({
            "row": None,
            "severity": "error",
            "code": "no_records",
            "message": "В таблице Fandom не найдены строки моделей с распознанными Toy #.",
        })

    error_count = sum(issue["severity"] == "error" for issue in issues)
    warning_count = sum(issue["severity"] == "warning" for issue in issues)
    return {
        "importer": "mainline",
        "source_format": "fandom_yearly_html",
        "mode": "preview_only",
        "writes_to_catalog": False,
        "catalog_year": catalog_year,
        "source_title": title or None,
        "records": records,
        "issues": issues,
        "summary": {
            "records_found": len(records),
            "errors": error_count,
            "warnings": warning_count,
            "ready_for_review": error_count == 0,
        },
    }

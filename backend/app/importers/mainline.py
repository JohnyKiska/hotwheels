"""Safe preview parser for pasted Hot Wheels Mainline checklist rows.

This module deliberately does not write to the catalog database. It turns the
legacy converter's tab-separated clipboard format into reviewable candidates.
"""
from __future__ import annotations

import re
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

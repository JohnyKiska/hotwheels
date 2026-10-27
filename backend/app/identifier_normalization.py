"""Conservative normalization for Hot Wheels catalog identifiers.

Normalization supports lookup only. It never establishes that two catalog records
represent the same casting or release.
"""
from __future__ import annotations

import re
import unicodedata


class InvalidIdentifier(ValueError):
    """Raised when an identifier is empty or invalid for its namespace."""


_DIGIT_ONLY_TYPES = {"upc", "ean"}
_WHITESPACE = re.compile(r"\s+")


def normalize_identifier(type_code: str, value: str) -> str:
    """Return a stable lookup key without discarding meaningful identifier data.

    UPC/EAN separators are removed but leading zeroes are preserved. Product
    numbers and SKUs are case-insensitive and have surrounding/internal spacing
    normalized; punctuation such as hyphens is retained.
    """
    if not isinstance(type_code, str) or not type_code.strip():
        raise InvalidIdentifier("Identifier type is required")
    if not isinstance(value, str):
        raise InvalidIdentifier("Identifier value must be text")

    code = type_code.strip().casefold()
    raw = unicodedata.normalize("NFKC", value).strip()
    if not raw:
        raise InvalidIdentifier("Identifier value cannot be empty")

    if code in _DIGIT_ONLY_TYPES:
        normalized = re.sub(r"[\s-]", "", raw)
        if not normalized.isascii() or not normalized.isdigit():
            raise InvalidIdentifier(f"{code.upper()} must contain only digits and separators")
        return normalized

    # Case folding handles ASCII catalog codes and Unicode consistently.
    normalized = _WHITESPACE.sub(" ", raw).casefold().upper()
    if not normalized:
        raise InvalidIdentifier("Identifier value cannot be empty")
    return normalized

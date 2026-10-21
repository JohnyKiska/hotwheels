#!/usr/bin/env python3
"""Read-only integrity checks for the existing Hot Wheels catalog."""
import json
from collections import Counter
from pathlib import Path

CATALOG = Path("collection.json")
REQUIRED = ("id", "toyNum", "name", "year", "seriesName", "status")
ALLOWED_STATUSES = {"missing", "owned"}


def main():
    records = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit("collection.json must contain a JSON array")

    ids = []
    missing_fields = []
    invalid_statuses = []

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SystemExit(f"Record {index} is not a JSON object")

        for field in REQUIRED:
            if field not in record or record[field] in (None, ""):
                missing_fields.append((index, field))

        if "id" in record:
            ids.append(str(record["id"]))

        if record.get("status") not in ALLOWED_STATUSES:
            invalid_statuses.append((index, record.get("status")))

    duplicate_ids = sorted(value for value, count in Counter(ids).items() if count > 1)

    print(f"Records: {len(records)}")
    print(f"Duplicate IDs: {len(duplicate_ids)}")
    print(f"Missing required fields: {len(missing_fields)}")
    print(f"Unexpected statuses: {len(invalid_statuses)}")

    if duplicate_ids:
        print("Duplicate ID examples:", duplicate_ids[:10])
        print("ERROR: duplicate IDs can cause actions to target the wrong car.")
    if missing_fields:
        print("Missing field examples:", missing_fields[:10])
    if invalid_statuses:
        print("Unexpected status examples:", invalid_statuses[:10])

    if duplicate_ids or missing_fields or invalid_statuses:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

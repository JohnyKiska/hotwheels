# Mainline Importer: isolated database pilot

**Status:** implementation branch, pending CI and review. The importer is not connected to a production database or public API.

## What it does

`backend/scripts/import_mainline.py` can fetch a yearly Hot Wheels Wiki Mainline table through the MediaWiki API, parse a saved HTML file, or consume an existing parsed snapshot JSON. It sends the parsed rows to `app.mainline_importer`.

The importer creates candidate Castings, Releases, Series, SKU and collector-number identifiers, source snapshots, pending Evidence, and catalog-tree placements. It deliberately preserves the source's raw row and annotation fields.

- Candidate records are not automatically confirmed.
- Evidence starts with `review_status=pending`.
- SKU is a lookup identifier, not a guarantee of unique release identity.
- Source `Col. #` is stored as a structured `catalog_number` identifier and linked to the Release as a secondary identifier; the source observation is also retained as pending Evidence.
- Collector numbers may repeat across releases or years. They are not globally unique and must not be used alone to merge or split Castings or Releases.
- Color annotations such as `(2nd Color)` produce separate Releases. A shared Casting grouping is only a candidate.
- Existing catalog fields are never overwritten.
- Re-running an unchanged source row is idempotent.
- A changed row creates a new source snapshot and evidence without silently overwriting the prior catalog values.
- Duplicate SKUs are reported; they are not merged.

## Dry run (default)

Run from the `backend` directory after installing `backend/requirements.txt` and applying Alembic migrations to an isolated test database:

```bash
python scripts/import_mainline.py --year 2024 --report-output mainline-2024-dry-run.json
```

The command fetches the Fandom table, exercises the importer inside a database transaction, then rolls the transaction back. The JSON report is written to the requested path.

For offline parsing from a saved Fandom HTML file:

```bash
python scripts/import_mainline.py --year 2024 --html-file /path/to/List-of-2024-Hot-Wheels.html
```

## Explicit write to an isolated SQLite test database

Writes are blocked unless all conditions are met:

1. `DATABASE_URL` is explicitly set to an SQLite database.
2. Its URL/path contains `test` or `sandbox`.
3. `HW_IMPORT_ALLOW_WRITE=1` is set.
4. `--apply` is supplied.

Example:

```bash
DATABASE_URL="sqlite:////absolute/path/to/hotwheels_test.db" alembic upgrade head
DATABASE_URL="sqlite:////absolute/path/to/hotwheels_test.db" HW_IMPORT_ALLOW_WRITE=1 \\\
  python scripts/import_mainline.py --year 2024 --apply --report-output mainline-2024-import.json
```

Do not point this pilot at a production database. It currently writes to the database configured for that process and is not an API endpoint.

## First verification target

Use the 2024 Mainline table as the first broad seed because we already have a comparison sample of five AllHW pages for that year: HRY49, HTD01, HTC50, HTF81, and HTF65. The database import currently uses Fandom as the bulk list source; AllHW enrichment and cross-source conflict review remain separate steps.

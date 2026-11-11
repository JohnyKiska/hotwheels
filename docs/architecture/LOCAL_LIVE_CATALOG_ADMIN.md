# Local live catalog admin

## Purpose

The repository root `index.html` remains the public visual prototype and contains hard-coded demonstration records. It is not connected to the backend.

This feature adds a separate local admin page at `/admin`, served by FastAPI from the same origin as its API. It reads existing database records and does not create, edit, confirm, merge, split, migrate, or delete catalog data.

## Endpoints

- `GET /catalog/admin/summary`: totals, status distributions, years, and source names.
- `GET /catalog/admin/releases`: searchable and paginated Release rows with Casting, SKU, catalog number, series, and Evidence count.
- `GET /catalog/admin/releases/{release_id}`: one Release with identifiers, series, Evidence, SourceRecord provenance, source URL, and raw source snapshot.
- `GET /admin`: local browser interface.

All catalog endpoints are SELECT-only and return `writes_to_catalog=false`. The page uses same-origin relative requests. No CORS policy is added and the GitHub Pages prototype is not connected to this API.

## Local run against the audited 2024 database

Use the existing `hotwheels_import_test_v2.db` file, not the zero-byte `hotwheels.db`. From the repository's backend directory in Windows CMD:

```cmd
set DATABASE_URL=sqlite:///E:/HW-CATALOG/backend/hotwheels_import_test_v2.db
python -m uvicorn app.main:app --reload --port 8000
```

Adjust the absolute path if the clone or database is stored elsewhere. Open:

```text
http://127.0.0.1:8000/admin
```

The environment variable applies only to that CMD window. Start the server locally and do not expose this development backend to the public internet: the wider API still contains separate write-capable conflict-resolution routes and authentication has not been implemented.

## Expected snapshot

The audited `mainline_2024_export.json` snapshot was exported from `hotwheels_import_test_v2.db` in read-only mode. It contains 441 Releases, 249 Castings, 36 Series, 441 SourceRecords, 2,646 Evidence rows, 691 CatalogIdentifiers, and 882 ReleaseIdentifier links. All 2,646 Evidence rows are pending review. The live page should show the same core totals when pointed at that matching database.

The current canonical ORM intentionally does not model legacy ProductLine/CatalogNode navigation yet. The first live view therefore browses Release records and their existing relationships without pretending that the full hierarchy has been migrated.

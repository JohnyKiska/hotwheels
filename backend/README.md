# Hot Wheels Catalog — Backend

Initial backend foundation for the test catalog.

## Stack

- Python
- FastAPI
- SQLAlchemy
- Alembic for versioned database schema migrations
- SQLite for local development
- pytest

## Current status

The backend has a FastAPI health endpoint, SQLite connection configuration, core
SQLAlchemy models, versioned Alembic migrations, and automated tests. No catalog
records are imported and no database file is committed.

## Core model rules

- `Casting` represents the underlying casting identity, not an individual year's release.
- `CastingVariant` represents a supported construction variant of a casting.
- `Release` represents a release in an official catalog year. The year may be unknown
  for a candidate record; the casting variant may also remain unknown until evidence supports it.
- A database constraint prevents a release from referencing a variant belonging to a different casting.
- A release can be linked to multiple `Series` records through `ReleaseSeries`.
  Series membership alone does not create a new release.
- IDs are opaque UUIDs and do not depend on names, years, SKUs, or UPCs.
- Record status is separate from the certainty of individual fields; source assertions,
  evidence, identifiers, conflicts, and audit history are modeled separately.
- The existing root-level `collection.json` is not modified or imported automatically.

## Run locally

From this directory:

```bash
python -m pip install -r requirements.txt
alembic upgrade head
pytest
uvicorn app.main:app --reload
```

Then open `/health` or `/docs` on the local server.

By default, the application and Alembic use the same local database file:
`backend/hotwheels.db`. The application and migrations both honor the
`DATABASE_URL` environment variable, so they can be pointed at the same
explicit database when needed.

For example, on macOS/Linux:

```bash
DATABASE_URL="sqlite:////absolute/path/to/hotwheels.db" alembic upgrade head
DATABASE_URL="sqlite:////absolute/path/to/hotwheels.db" uvicorn app.main:app --reload
```

Keep the URL identical for migrations and the running application. The example
above uses an absolute SQLite path; the database file should remain local and
must not be committed.

## Initialize a local SQLite database (development bootstrap only)

Only use this when you explicitly want to create tables from the current ORM
metadata instead of applying versioned migrations:

```bash
python -m app.init_db
```

This creates tables but does not import catalog data. For the normal project
workflow, prefer `alembic upgrade head` so the database schema follows the
versioned migration history. The generated `backend/hotwheels.db` file should
remain local and must not be committed.

## Browser UI and CORS

The catalog-tree page can be opened from a separate local or hosted origin.
Configure the exact browser origins allowed to call the API using the
comma-separated `HW_CORS_ORIGINS` environment variable:

```bash
HW_CORS_ORIGINS="http://localhost:5500,http://127.0.0.1:5500" uvicorn app.main:app --reload
```

For a hosted preview, add its exact origin (scheme and host, without a path) to
`HW_CORS_ORIGINS`. Do not use `*` for public deployments. The default only
permits common local development origins; it does not automatically trust GitHub
Pages or HTML Preview. CORS is a browser access policy, not authentication or
API access control.

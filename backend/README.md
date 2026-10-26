# Hot Wheels Catalog — Backend

Initial backend foundation for the test catalog.

## Stack

- Python
- FastAPI
- SQLAlchemy
- Alembic (versioned schema migrations are a later database step)
- SQLite
- pytest

## Current status

The backend has a minimal FastAPI health endpoint, SQLite connection configuration,
core SQLAlchemy models, and initial tests. The tests have been added to the repository,
but must be run in a Python environment before they can be reported as passing.
No catalog records are imported and no database file is committed.

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
  evidence, identifiers, conflicts, and audit history will be added as separate models.
- The existing root-level `collection.json` is not modified or imported automatically.

## Run locally

From this directory:

```bash
python -m pip install -r requirements.txt
pytest
uvicorn app.main:app --reload
```

Then open `/health` or `/docs` on the local server.

## Initialize a local SQLite database

Only do this when you explicitly want to create the local database file:

```bash
python -m app.init_db
```

This creates tables for the current models, but does not import catalog data. It is
a development bootstrap, not a replacement for versioned Alembic migrations. The
generated `backend/hotwheels.db` file should remain local and must not be committed.

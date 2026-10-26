# Hot Wheels Catalog — Backend

Initial backend foundation for the test catalog.

## Stack

- Python
- FastAPI
- SQLAlchemy
- Alembic (versioned schema migrations are the next database step)
- SQLite
- pytest

## Current status

The backend has a minimal FastAPI health endpoint, SQLite connection configuration,
and the first SQLAlchemy models for the core catalog entities. This is a schema
foundation only: no catalog records are imported and no database file is committed.

## Core model rules

- `Casting` represents the underlying casting identity, not an individual year's release.
- `CastingVariant` represents a supported construction variant of a casting.
- `Release` represents a release in an official catalog year. The year may be unknown
  for a candidate record; the casting variant may also remain unknown until evidence supports it.
- A release can be linked to multiple `Series` records through `ReleaseSeries`.
  Series membership alone does not create a new release.
- IDs are opaque UUIDs and do not depend on names, years, SKUs, or UPCs.
- Record status is kept separate from the certainty of individual fields; detailed
  source assertions, evidence, identifiers, conflicts, and audit history will be added
  as separate models.
- The existing root-level `collection.json` is not modified or imported automatically.

## Run locally

From this directory:

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open `/health` or `/docs` on the local server.

## Initialize a local SQLite database

Only do this when you explicitly want to create the local database file:

```bash
python -m pip install -r requirements.txt
python -m app.init_db
```

This creates the tables defined by the current models, but does not import catalog
data. It is a development bootstrap, not a replacement for versioned Alembic
migrations. The generated `backend/hotwheels.db` file should remain local and must
not be committed.

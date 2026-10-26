# Hot Wheels Catalog — Backend

Initial backend foundation for the test catalog.

## Stack

- Python
- FastAPI
- SQLAlchemy
- Alembic
- SQLite (database configuration will be added in the next step)
- pytest

## Current status

This foundation contains a minimal FastAPI application and a health endpoint. It does not yet create a database or import catalog data.

## Data safety rules

- The existing root-level `collection.json` is not modified or imported automatically.
- Catalog entities will use stable internal IDs.
- Source assertions and evidence will be stored separately from accepted catalog values.
- Ambiguous identity decisions require human review.
- Schema changes will be versioned with Alembic migrations.

## Run locally

From this directory, install dependencies and start the development server:

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open `/health` or `/docs` on the local server.


## SQLite model foundation

Initial model files are being added incrementally. The database will be created locally only when explicitly initialized; no database file is committed. The existing root-level `collection.json` is not imported or modified.

Local bootstrap (once the model files are present):

```bash
python -m pip install -r requirements.txt
python -m app.init_db
uvicorn app.main:app --reload
```

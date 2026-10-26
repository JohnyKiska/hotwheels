# Database migrations

The initial core schema is currently created by `backend/app/init_db.py`. The evidence-layer migration is an Alembic revision under `versions/`; it adds only source/evidence/media/conflict/history tables and does not change existing casting/release tables or import `collection.json`.

Before using Alembic on a persistent database, configure `alembic.ini` and `env.py` to load `app.models` and `app.db.Base.metadata`. The revision is metadata-driven and therefore must run with the same application version that defines these tables. Fresh test databases continue to use `Base.metadata.create_all`.

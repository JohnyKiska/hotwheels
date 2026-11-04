# Database migrations

Run commands from `backend/`:

```bash
python -m pip install -r requirements.txt
alembic upgrade head
alembic current
```

Alembic uses the same database URL resolver as the application:

1. `DATABASE_URL` is an explicit override (used by tests and controlled deployments).
2. `HW_CATALOG_DATA_DIR` selects an initialized external storage root and resolves
   to `DATABASE/catalog.db`.
3. Otherwise, the configured Alembic URL is used. The checked-in default,
   `sqlite:///hotwheels.db`, is relative to `backend/`.

For external storage, the root must already contain a valid `DEVICE_INFO.json`
marker and an existing `DATABASE/` directory. See the backend README for the
marker format and safety behavior. Back up persistent data before applying migrations.

The initial core schema is currently also supported by `python -m app.init_db`.
The evidence-layer revision adds source/evidence/media/conflict/history tables only;
it does not alter casting/release tables or import `collection.json`. It uses
SQLAlchemy metadata with `checkfirst`, so it can run either against a database
where core tables were created by `init_db` or a fresh empty SQLite database.
The migration environment imports the same model metadata as the application.

**Important:** downgrading the evidence-layer revision drops those tables and their
data. Do not use `alembic downgrade -1` on a database with evidence you need to keep.
The migration is not yet a baseline migration for the original core tables; those
tables are initialized by `app.init_db`. This revision establishes the Alembic
version marker for the current schema and adds the evidence layer.

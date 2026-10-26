# Database migrations

Run commands from `backend/`:

```bash
python -m pip install -r requirements.txt
alembic upgrade head
alembic current
```

The database URL defaults to `sqlite:///hotwheels.db` relative to `backend/`. Set
`DATABASE_URL` to target a different database (especially for tests and staging).
Back up a persistent database before applying migrations.

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

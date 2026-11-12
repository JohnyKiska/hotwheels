# Hot Wheels Catalog — Backend

Backend foundation for the Hot Wheels catalog.

## Stack

- Python
- FastAPI
- SQLAlchemy
- Alembic
- SQLite
- pytest

## Current status

The backend provides the catalog API, SQLAlchemy models, evidence and conflict
workflows, and read-only import previews. No catalog records are imported
automatically and no database file belongs in Git.

## Core model rules

- `Casting` represents the underlying casting identity, not an individual year's release.
- `CastingVariant` represents a supported construction variant of a casting.
- `Release` represents a release in an official catalog year. The year and casting
  variant may remain unknown until evidence supports them.
- A release can be linked to multiple `Series` records through `ReleaseSeries`.
  Series membership alone does not create a new release.
- IDs are opaque UUIDs and do not depend on names, years, SKUs, or UPCs.
- Source assertions, evidence, identifiers, conflicts, and audit history are kept
  separately from catalog identity.
- The root-level `collection.json` is not modified or imported automatically.

## Run locally

From this directory:

```bash
python -m pip install -r requirements.txt
pytest
uvicorn app.main:app --reload
```

Then open `/health` or `/docs` on the local server.

## Database location

The application and Alembic use the same database URL resolver.

Configuration priority:

1. `DATABASE_URL`: explicit URL override, retained for tests and controlled deployments.
2. `HW_CATALOG_DATA_DIR`: initialized external catalog storage root.
3. Development default: `backend/hotwheels.db` (legacy location).

For external storage, set an absolute path to the `HW-CATALOG` directory, for example:

```env
HW_CATALOG_DATA_DIR=H:\HW-CATALOG
```

The directory must already exist and contain:

```text
HW-CATALOG/
├── DEVICE_INFO.json
└── DATABASE/
    └── catalog.db
```

The marker must be a JSON object with a UUID `storage_id` and
`"layout_version": 1`. The backend validates the marker and existing `DATABASE`
directory at startup. It never creates a missing external directory, marker, or
database folder automatically. A missing or disconnected drive therefore fails
closed instead of silently falling back to a new local database.

The explicit `DATABASE_URL` override takes precedence over
`HW_CATALOG_DATA_DIR`; do not set both in normal external-storage operation.

## Initialize external storage

On the PC where the HDD or SSD is connected, run this once from `backend/`:

```bash
python -m app.init_storage "H:\HW-CATALOG" --label "Development HDD"
```

Use the actual drive letter assigned by Windows. The command creates the storage
folders and `DEVICE_INFO.json`, but does not create a database or import catalog
records. It refuses to modify a non-empty target directory. After initialization,
set `HW_CATALOG_DATA_DIR` to that directory before starting the backend.

## Initialize a development database

Only when you explicitly want to create the legacy local development database:

```bash
python -m app.init_db
```

This creates tables for the current models but does not import catalog data. It is
a development bootstrap, not a replacement for versioned Alembic migrations.
The generated database and all local storage data must remain outside Git.

## Transactional email worker

The account invitation and email-verification flows enqueue encrypted messages
in the transactional outbox. Sending is performed by a separate worker process,
not by API requests.

Install dependencies and configure these server-side environment variables:

- `HW_EMAIL_ENCRYPTION_KEY`: Fernet key used to encrypt outbox payloads.
  Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- `HW_SMTP_HOST` and `HW_SMTP_FROM_EMAIL`: required SMTP server and sender.
- `HW_SMTP_PORT`: defaults to 587.
- `HW_SMTP_SECURITY`: `starttls` (default), `ssl`, or explicitly `none`.
- `HW_SMTP_USERNAME` and `HW_SMTP_PASSWORD`: optional, but must be set together.
- `HW_SMTP_FROM_NAME`: defaults to `HW Catalog`.
- `HW_SMTP_TIMEOUT`: connection timeout in seconds, defaults to 20.
- `DATABASE_URL` or the normal catalog database location settings.

Run one batch:

```bash
python -m app.email_worker --once
```

Run continuously:

```bash
python -m app.email_worker --poll-seconds 5 --batch-size 20
```

Run the worker as a separate supervised process/service. Do not run it inside
each API worker process. Keep SMTP credentials and encryption keys in the
hosting provider's secret store, never in Git or frontend configuration.

The dispatcher retries transient errors with bounded exponential backoff.
SMTP cannot guarantee exactly-once delivery if a connection drops after the
server accepted a message; the worker therefore provides at-least-once delivery
in that edge case. The idempotency key is included as a diagnostic header, but
SMTP servers are not required to deduplicate it.

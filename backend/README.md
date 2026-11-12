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

## OAuth sign-in and identity linking

GitHub OAuth and Google OpenID Connect use authorization-code flow with PKCE.
The API stores only a hash of OAuth state, a hash of the Google nonce, and an
encrypted PKCE verifier in a short-lived, single-use database transaction.

Required server-side secrets/configuration:

- `HW_OAUTH_ENCRYPTION_KEY`: independent Fernet key for encrypting PKCE verifiers.
  Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- `HW_GITHUB_CLIENT_ID` and `HW_GITHUB_CLIENT_SECRET`.
- `HW_GITHUB_REDIRECT_URI`: exact callback URL
  `/api/v1/account/oauth/github/callback`.
- `HW_GOOGLE_CLIENT_ID` and `HW_GOOGLE_CLIENT_SECRET`.
- `HW_GOOGLE_REDIRECT_URI`: exact callback URL
  `/api/v1/account/oauth/google/callback`.
- `HW_FRONTEND_URL`: frontend origin used for the final redirect. If omitted,
  `HW_PUBLIC_BASE_URL` is used.

Login starts at `GET /api/v1/account/oauth/{github|google}/start`.
An already authenticated user links a provider through
`POST /api/v1/account/oauth/{github|google}/link`, with the normal Origin and
CSRF headers. The callback is
`GET /api/v1/account/oauth/{github|google}/callback`.

A login succeeds only when the provider subject is already linked to an active
HW Catalog user. Provider email equality never merges or links accounts.
New users remain invite-only: accept an invitation first, then link a provider.
The link callback is bound to the initiating HW Catalog session.

Google ID tokens are verified against Google's published signing keys, issuer,
audience, expiry and nonce. GitHub identity uses the immutable numeric account
ID returned by the authenticated API, not the mutable username. OAuth client
secrets and encryption keys belong only in the hosting secret store.

## Email/password sign-in and recovery

Email/password sign-in is available for an existing account after its primary
email is verified and a password has been configured. Registration remains
invite-only: accept an invitation, then while signed in call
`POST /api/v1/account/password/set` with the normal Origin and CSRF headers.
Password setup is one-time; an existing password cannot be overwritten through
this endpoint.

Endpoints:

- `POST /api/v1/account/password/login`: email/password login; returns a
  generic error for unknown, unverified, disabled, suspended or invalid accounts.
- `POST /api/v1/account/password/set`: configure the first password for the
  authenticated user with a verified primary email.
- `POST /api/v1/account/password/change`: change an existing password after
  verifying the current password; other active sessions and pending reset links
  are revoked while the current browser session remains active.
- `POST /api/v1/account/password/reset/request`: enumeration-safe reset request;
  always returns HTTP 202 with the same response.
- `POST /api/v1/account/password/reset/confirm`: consume a single-use reset
  token and set a new password. Successful reset revokes all existing sessions.

Passwords are hashed with Argon2id. Reset tokens are random, single-use,
30-minute tokens stored only as SHA-256 hashes. Reset URLs are placed only in
the encrypted transactional email outbox. Rate-limit buckets are persistent
and store keyed HMAC digests rather than raw email addresses or IP addresses.
The login threshold is five failures per email bucket and twelve per IP bucket
within a 15-minute window; a blocked bucket remains blocked for 15 minutes.

Configure the server-side secret `HW_AUTH_RATE_LIMIT_KEY` with at least 32
random characters. It is used to HMAC privacy-preserving rate-limit bucket
identifiers. Also configure `HW_EMAIL_ENCRYPTION_KEY`,
`HW_PUBLIC_BASE_URL`, and the SMTP settings documented above. Never expose
these values to the frontend or commit them to Git.


## Account frontend

The static account interface is `../login.html` at the repository root and is
linked from the catalog header. It supports email/password login, Google/GitHub
OAuth login, invitation acceptance and first-password setup, password reset,
password change, account profile, and linking an external identity.

The frontend uses same-origin `/api/v1` by default. For production, serve the
static site and FastAPI behind the same HTTPS origin, reverse-proxying
`/api/*` to FastAPI. If a separate API origin is unavoidable, set the
`hw-api-base` meta tag in `login.html` to the API origin and configure a
credentialed CORS allowlist, cookie SameSite/domain policy, and CSRF protections
before exposing it publicly. Do not put OAuth client secrets or other server
secrets in the HTML.

Set `HW_FRONTEND_URL` to the public static-site origin. OAuth callback results,
invitation links, email-verification links and password-reset links return to
`/login.html` with short-lived status/token query parameters. Token-bearing
emails remain encrypted in the transactional outbox.

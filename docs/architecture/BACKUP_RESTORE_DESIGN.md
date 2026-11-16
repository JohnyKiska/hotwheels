# HW Catalog Backup and Restore Design

Status: design baseline, 2026-11-16.
Scope: Windows PowerShell workflow for the portable external data directory.

## Goals

- Create a consistent, independently verifiable snapshot of user data.
- Keep the working external HDD and the backup destination separate.
- Preserve previous known-good snapshots until a newer snapshot is fully verified.
- Restore only into a new or explicitly empty directory; never overwrite the live storage.
- Make the workflow independent of drive letters and machine-specific storage IDs.

## Current verified baseline

- The working SQLite database is `DATABASE/catalog.db` on the external HDD.
- `BACKUPS/manual/catalog-initial-20261113.db` passed SQLite `integrity_check`.
- A temporary restore copy passed `integrity_check`, contained 40 tables, and had the same SHA-256 as the source backup.
- The main database and initial backup have different SHA-256 values. Both passed integrity checks.
- No SQLite WAL/SHM sidecar files were found during the 2026-11-16 inspection.
- No independent physical backup currently exists.

## Agreed storage plan

1. The external HDD remains the working storage device and may retain local backup snapshots.
2. The home PC's internal disk has approximately 800 GB reserved as the future backup destination.
3. A separate portable SSD will be used to transport backup snapshots between work and home when it becomes necessary.
4. The portable SSD purchase is deferred until there is a real need. The sole working HDD must not be treated as an independent transport/backup device.
5. The home-PC destination is not considered a backup until a verified copy has actually been transferred there.

## Snapshot contents

A snapshot contains these data areas when present:

- `DATABASE/catalog.db`
- `MEDIA/`
- `IMPORTS/`
- `EXPORTS/`

The snapshot does not recursively include `BACKUPS/` or transient `LOGS/`. It does not copy `DEVICE_INFO.json`: that file identifies a particular initialized storage device and must not be cloned as the identity of another device. The manifest records the source layout version, but not the source storage UUID.

Application code, virtual environments, credentials, local environment files, PID files, and machine-specific settings are not part of the data snapshot. They are managed separately through Git or local configuration.

## Backup workflow contract

The PowerShell backup command must:

1. Require explicit source and destination roots; never infer a drive letter.
2. Resolve both paths and refuse identical paths, a destination inside the source, or a source inside the destination.
3. Refuse to run if the HW Catalog backend PID record indicates a live backend process for the source storage. It must not stop or kill processes automatically.
4. Require the source marker and expected directory layout; fail closed if the source is incomplete.
5. Create a new timestamped snapshot directory. Never overwrite an existing snapshot.
6. Use Python's SQLite `Connection.backup()` API to create the snapshot database, rather than copying a potentially active SQLite file with a generic file-copy command.
7. Copy the media/import/export trees without following reparse points or silently skipping errors.
8. Generate SHA-256 hashes for every snapshot file and a JSON manifest containing the creation time, relative paths, byte sizes, hashes, and snapshot format version.
9. Run SQLite `PRAGMA integrity_check` against the snapshot database in read-only mode.
10. Re-read and verify the manifest hashes after the copy. A failed check marks the snapshot failed and must not prune older snapshots.
11. Never delete older snapshots as part of the initial implementation. Retention/pruning is a separate future operation requiring an explicit dry-run and confirmation.

## Restore workflow contract

The restore command must:

1. Require an explicit snapshot directory and a new destination path.
2. Refuse an existing non-empty destination. It must never target the current working storage root.
3. Validate the manifest schema, relative paths, file sizes, and SHA-256 hashes before writing.
4. Reject absolute paths, parent traversal segments, and reparse-point escapes.
5. Recreate the data directories and copy only the manifest-listed files.
6. Generate a fresh destination `DEVICE_INFO.json` only through the existing storage initialization mechanism; never reuse the source device identity.
7. Run SQLite `integrity_check` on the restored database and verify all restored file hashes.
8. Leave the destination isolated and inactive. Switching the application to restored data remains a separate, explicit operator action.
9. Never modify or delete the source snapshot.

## Safety invariants

- No script overwrites the live `DATABASE/catalog.db`.
- No script automatically deletes an existing snapshot.
- No script kills the backend process.
- No restore runs against a non-empty destination.
- A copy on the same physical HDD is a local recovery copy, not protection against failure of that HDD.
- A snapshot is not marked verified until its manifest hashes and SQLite integrity check pass.
- The current project scripts `start-hw-catalog.ps1` and `stop-hw-catalog.ps1` are out of scope and must not be modified by this work.

## Implementation sequence

1. Implement and test manifest/path validation helpers.
2. Implement backup creation with SQLite online backup API and post-copy verification.
3. Implement restore into a new empty directory with fresh storage identity.
4. Add automated tests for path traversal, existing destinations, corrupt hashes, missing files, SQLite corruption, and successful round-trip restore.
5. Document manual Windows validation on a disposable test storage before using the production HDD.
6. Only after local validation, plan transport to the home PC and independent-copy verification.

## Initial implementation

The first implementation is provided by:

- `backend/app/backup_restore.py`: Python standard-library implementation for SQLite online backup, SHA-256 manifest generation/verification, and restore.
- `scripts/windows/backup-hw-catalog.ps1`: Windows entry point. Requires explicit source/destination and the `-ConfirmBackendStopped` switch; checks known PID records and running uvicorn/app.main:app processes. It never stops or kills a process.
- `scripts/windows/restore-hw-catalog.ps1`: Windows entry point for restore into a new or empty destination.

Run from PowerShell at the repository root:

```powershell
.\scripts\windows\backup-hw-catalog.ps1 -SourceRoot "E:\HW-CATALOG-DATA" -DestinationRoot "C:\HW-CATALOG-BACKUP" -ConfirmBackendStopped
.\scripts\windows\restore-hw-catalog.ps1 -Snapshot "C:\HW-CATALOG-BACKUP\hw-catalog-<timestamp>" -DestinationRoot "C:\HW-CATALOG-RESTORE-TEST"
```

The backup command requires the operator to stop the backend first. The PID/CIM checks are additional guards, not a substitute for the explicit confirmation. A process started outside the standard launcher is also checked by its command line; if process inspection fails, backup fails closed.

The implementation rejects symlinks/reparse points, nested source/destination paths, restore targets inside any initialized storage tree, unexpected manifest paths, missing/extra payload files, hash/size mismatches, and SQLite integrity failures. Restore validates the entire snapshot before writing, initializes a fresh storage identity, copies only manifest-listed files, and leaves a `.RESTORE_INCOMPLETE` marker if an error occurs after writing begins. It does not clean up a partial restore automatically.

Automated tests are in `backend/tests/test_backup_restore.py`. They cover round-trip restore, fresh storage identity, nested paths, non-empty destinations, tampering, missing files, path traversal, and SQLite corruption.

## Open implementation detail

The backend currently stores the external database at `DATABASE/catalog.db` and validates `DEVICE_INFO.json` with layout version 1. The implementation preserves this layout without copying the source device UUID. The first version intentionally has no retention/pruning command.

## Manual Windows validation (2026-11-16)

The PowerShell entry points were exercised on a disposable synthetic storage under the Windows temporary directory. The production external HDD, its database, and the repository's local working data were not used or modified by the test.

Environment and setup:
- Python 3.13.17 was available.
- No running `uvicorn app.main:app` backend process was detected before the test.
- Synthetic storage was initialized with a SQLite database and one sample file in each of `MEDIA`, `IMPORTS`, and `EXPORTS`.
- The scripts were initially downloaded as UTF-8 without a BOM. Windows PowerShell failed to parse the Russian text. Adding a UTF-8 BOM to the disposable copies resolved the parser error. The repository scripts now include a UTF-8 BOM for Windows PowerShell 5.1 compatibility.

Successful backup/restore:
- The PowerShell backup wrapper created a timestamped snapshot containing `DATABASE/catalog.db`, `MEDIA/images/sample.txt`, `IMPORTS/mainline/sample.csv`, `EXPORTS/sample.txt`, and `manifest.json`.
- The PowerShell restore wrapper restored the snapshot into a separate empty directory and wrote `RESTORE_VERIFIED.txt`; `.RESTORE_INCOMPLETE` was absent.
- The restored storage received a new `storage_id`, distinct from the synthetic source.
- Both source and restored SQLite databases returned `PRAGMA integrity_check = ok` and contained the expected sample row.
- All four payload files matched their manifest sizes and SHA-256 hashes in both the snapshot and restored storage.
- The source and restored copies of the three non-database sample files matched byte-for-byte.

Negative-path checks:
- Restore refused a non-empty destination. A sentinel file in that destination remained unchanged.
- A separate copy of the snapshot was tampered with by changing the size of `EXPORTS/sample.txt`. Restore rejected it with a size-mismatch error before writing restored data.
- The original successful snapshot remained unchanged.

Result:
- The backup/restore round-trip and the tested safety checks passed on disposable Windows data.
- This manual test does not establish the existence of an independent backup of production data, does not validate a real backup from the external HDD, and does not replace a future restore rehearsal using a separately stored production snapshot.
- PowerShell process-detection behavior was exercised with no backend process running; the active-backend refusal path was not deliberately triggered in this manual test.

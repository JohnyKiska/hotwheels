# External storage synchronization

**Updated:** 2026-11-17  
**Canonical code/docs source:** GitHub, branch `integration/catalog-foundation`  
**External data drive:** `E:\HW-CATALOG-DATA` (ADATA SH93, FAT32; verify the actual drive letter before use)

## 1. Two different kinds of data

The external drive is not a mirror of the Git repository.

| Data | Canonical location | Sync policy |
|---|---|---|
| Source code, docs, Project Manager state | GitHub `integration/catalog-foundation` | Git pull first; selected portable Project Manager snapshot may be copied to the drive |
| SQLite database | `HW-CATALOG-DATA/DATABASE/catalog.db` | Remains external; never copied into Git |
| Media originals and thumbnails | `HW-CATALOG-DATA/MEDIA/` | Stored outside Git; backup/restore must be handled separately |
| Imports, exports, backups | Corresponding external-drive folders | No blanket mirror or cleanup |
| Secrets and machine-specific settings | Local machine / secret store | Never sync to Git or the portable Project Manager snapshot |
| Device identity | `DEVICE_INFO.json` | Never overwrite or regenerate during synchronization |

Do not use a whole-repository copy, bidirectional sync, or a generic mirror command against the root of the external drive.

## 2. Project Manager snapshot

Only these four files are copied into `HW-CATALOG-DATA/PROJECT-MANAGEMENT/`:

- `index.html`
- `project-state.json`
- `project-state.schema.json`
- `README.md`

GitHub remains canonical. The external folder is a portable, read-only-in-principle snapshot for convenient access on another computer. Edit the canonical state in GitHub workflow, not by independently editing the external copy.

The guarded script is:

`scripts/windows/sync-project-manager-to-external.ps1`

Run it from a clean local checkout after the documentation PR has been merged and the local integration branch has been updated:

```powershell
git switch integration/catalog-foundation
git pull --ff-only
git status --short
.\scripts\windows\sync-project-manager-to-external.ps1 -RepositoryRoot (Get-Location).Path -DataRoot 'E:\HW-CATALOG-DATA'
```

The script:
1. Requires the integration branch and a clean Git working tree.
2. Checks that the selected drive is mounted and contains `DEVICE_INFO.json`, the expected storage layout and required data directories.
3. Copies only the four Project Manager files into a staging directory.
4. Verifies SHA-256 for every staged file.
5. Preserves the previous snapshot under a timestamped `PROJECT-MANAGEMENT.previous.*` directory.
6. Promotes the staged snapshot and verifies SHA-256 again.

It does not write to or synchronize `DATABASE`, `MEDIA`, `IMPORTS`, `EXPORTS`, `BACKUPS`, `LOGS` or `DEVICE_INFO.json`. It does not delete previous snapshots. Review the script before first execution and confirm the drive letter.

## 3. Backend media path

The upload implementation proposed in PR #117 uses:

- `HW_CATALOG_MEDIA_DIR` when explicitly configured;
- otherwise `HW_CATALOG_DATA_DIR/MEDIA` when external storage is configured;
- otherwise `backend/media` for local development only.

If `HW_CATALOG_DATA_DIR` is explicitly set but the external storage identity or `MEDIA` directory is unavailable, media storage must fail closed. It must not silently fall back to a different local disk.

Expected media layout:

```text
HW-CATALOG-DATA/
  MEDIA/
    images/
    thumbnails/
```

Original images and thumbnails are separate files. Originals are preserved; thumbnails are generated derivatives. Binary media is not committed to Git or stored in the SQL database.

For Docker staging, media is stored in the persistent `media_data` volume. Include this volume in the deployment backup/restore procedure. A Docker volume is persistent storage, not an independent backup.

## 4. Safe work-session handoff between PCs

1. Stop the backend and any process using SQLite on the current PC.
2. Wait for writes to finish; do not copy an active SQLite database as an ordinary file.
3. Close applications that may keep files open, then safely eject the external drive.
4. Connect the drive to the second PC and verify its identity using `DEVICE_INFO.json`, not drive letter alone.
5. Start the backend only after confirming that `HW_CATALOG_DATA_DIR` points to this initialized drive.
6. Never run two writable backend instances against the same SQLite database at the same time.
7. Before unplugging, stop the backend and safely eject the drive again.

The Project Manager snapshot sync does not perform database backup, media backup, or full-drive synchronization.

## 5. Backup and restore boundary

The working HDD is not an independent physical backup. Keep the existing backup/restore workflow and its verification rules separate from Project Manager snapshot sync.

Before copying or restoring database/media data:
- use the documented SQLite-safe backup procedure;
- preserve the previous valid backup;
- verify the SHA-256 manifest;
- restore only into an explicitly selected empty destination;
- run SQLite `integrity_check` on a restored database;
- do not treat a same-drive copy as protection against drive failure.

The planned independent backup on another physical device remains a separate task. Do not improvise a transfer by overwriting the only working HDD.

## 6. Verified state as of 2026-11-17

- The external drive was previously audited read-only on 2026-11-16; the ALLHW import transfer was verified as 60/60 SHA-256 matches.
- This GitHub-side documentation work cannot inspect the current physical drive, current local Git working tree, or whether a new Project Manager snapshot has been copied.
- PR #117 contains the media upload/storage implementation and its latest CI checks passed, but the PR remains open until merged.
- The Project Manager snapshot sync script is prepared in the repository. It has not been run against the user's physical drive.


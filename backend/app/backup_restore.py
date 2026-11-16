"""Safe, portable backup and restore primitives for HW Catalog storage.

Run from the backend directory:
    python -m app.backup_restore backup --source ... --destination ... --confirm-backend-stopped
    python -m app.backup_restore restore --snapshot ... --destination ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .init_storage import initialize_storage

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
DATABASE_RELATIVE = "DATABASE/catalog.db"
ALLOWED_ROOTS = ("MEDIA", "IMPORTS", "EXPORTS")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class BackupRestoreError(RuntimeError):
    """Raised when a backup or restore safety check fails."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except AttributeError:
        return False
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise BackupRestoreError(f"Cannot inspect filesystem entry {path}: {exc}") from exc
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _raise_walk_error(error: OSError) -> None:
    raise error


def _walk_files(root: Path):
    for current, dirs, files in os.walk(
        root, followlinks=False, onerror=_raise_walk_error
    ):
        dirs.sort()
        for name in sorted(files):
            yield Path(current) / name


def _assert_no_reparse_points(root: Path) -> None:
    if _is_reparse_point(root):
        raise BackupRestoreError(f"Reparse point is not allowed: {root}")
    if root.is_dir():
        for current, dirs, files in os.walk(
            root, followlinks=False, onerror=_raise_walk_error
        ):
            current_path = Path(current)
            for name in dirs + files:
                candidate = current_path / name
                if _is_reparse_point(candidate):
                    raise BackupRestoreError(f"Reparse point is not allowed: {candidate}")


def _reject_reparse_in_path(path: str | Path) -> None:
    candidate = Path(os.path.abspath(Path(path).expanduser()))
    parts = [candidate, *candidate.parents]
    for item in reversed(parts):
        try:
            item.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise BackupRestoreError(f"Cannot inspect path component {item}: {exc}") from exc
        if _is_reparse_point(item):
            raise BackupRestoreError(f"Path contains a symlink or reparse point: {item}")


def _resolved(path: str | Path) -> Path:
    _reject_reparse_in_path(path)
    return Path(path).expanduser().resolve(strict=False)


def _assert_separate(source: Path, destination: Path) -> None:
    source_real = source.resolve(strict=True)
    destination_real = destination.resolve(strict=False)
    if source_real == destination_real or source_real in destination_real.parents or destination_real in source_real.parents:
        raise BackupRestoreError("Source and destination must be separate, non-nested directories.")


def _read_storage_marker(source: Path) -> dict:
    marker_path = source / "DEVICE_INFO.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupRestoreError(f"Cannot read DEVICE_INFO.json: {exc}") from exc
    if not isinstance(marker, dict) or marker.get("layout_version") != 1:
        raise BackupRestoreError("Unsupported or invalid DEVICE_INFO.json layout.")
    try:
        uuid.UUID(str(marker["storage_id"]))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise BackupRestoreError("DEVICE_INFO.json has no valid storage_id UUID.") from exc
    return marker


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_integrity(database: Path) -> None:
    if not database.is_file():
        raise BackupRestoreError(f"Snapshot database is missing: {database}")
    uri = f"file:{quote(str(database.resolve()).replace(os.sep, '/'))}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise BackupRestoreError(f"SQLite integrity check failed: {exc}") from exc
    if rows != [("ok",)]:
        raise BackupRestoreError(f"SQLite integrity_check returned: {rows!r}")


def _iter_payload_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for relative_root in ALLOWED_ROOTS:
        folder = root / relative_root
        if not folder.exists():
            continue
        if not folder.is_dir():
            raise BackupRestoreError(f"Expected a directory: {folder}")
        for current, dirs, names in os.walk(
            folder, followlinks=False, onerror=_raise_walk_error
        ):
            dirs.sort()
            names.sort()
            for name in names:
                path = Path(current) / name
                if not path.is_file():
                    raise BackupRestoreError(f"Unsupported non-file entry: {path}")
                files.append(path)
    database = root / DATABASE_RELATIVE
    if not database.is_file():
        raise BackupRestoreError(f"Required database is missing: {database}")
    files.append(database)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix().casefold())


def _copy_tree_files(source: Path, snapshot: Path, files: list[Path]) -> None:
    for source_file in files:
        relative = source_file.relative_to(source)
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.as_posix() == DATABASE_RELATIVE:
            source_uri = f"file:{quote(str(source_file.resolve()).replace(os.sep, '/'))}?mode=ro"
            try:
                with sqlite3.connect(source_uri, uri=True) as source_db:
                    with sqlite3.connect(target) as target_db:
                        source_db.backup(target_db)
                        target_db.commit()
            except sqlite3.DatabaseError as exc:
                raise BackupRestoreError(f"SQLite online backup failed: {exc}") from exc
            _sqlite_integrity(target)
        else:
            shutil.copy2(source_file, target)


def _build_manifest(snapshot: Path, source_marker: dict) -> dict:
    entries = []
    payload = list(_walk_files(snapshot))
    for path in sorted(payload, key=lambda item: item.relative_to(snapshot).as_posix().casefold()):
        relative = path.relative_to(snapshot).as_posix()
        entries.append({"path": relative, "size": path.stat().st_size, "sha256": _sha256(path)})
    return {
        "format_version": FORMAT_VERSION,
        "created_at_utc": _utc_now(),
        "source_layout_version": source_marker["layout_version"],
        "files": entries,
    }


def _safe_manifest_path(snapshot: Path, relative_text: str) -> Path:
    if not isinstance(relative_text, str) or not relative_text or "\\" in relative_text:
        raise BackupRestoreError("Manifest contains an invalid relative path.")
    relative = PurePosixPath(relative_text)
    if not relative.parts or relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        raise BackupRestoreError(f"Unsafe manifest path: {relative_text!r}")
    if relative.parts[0] not in ("DATABASE", *ALLOWED_ROOTS):
        raise BackupRestoreError(f"Manifest path is outside allowed data areas: {relative_text}")
    if relative.parts[0] == "DATABASE" and relative_text != DATABASE_RELATIVE:
        raise BackupRestoreError(f"Unexpected database-area path: {relative_text}")
    if relative_text == MANIFEST_NAME or relative_text == "DEVICE_INFO.json":
        raise BackupRestoreError(f"Forbidden manifest path: {relative_text}")
    candidate = snapshot.joinpath(*relative.parts)
    try:
        candidate.resolve(strict=False).relative_to(snapshot.resolve(strict=True))
    except ValueError as exc:
        raise BackupRestoreError(f"Manifest path escapes snapshot: {relative_text}") from exc
    return candidate


def verify_snapshot(snapshot_dir: str | Path) -> dict:
    snapshot = _resolved(snapshot_dir)
    if not snapshot.is_dir() or _is_reparse_point(snapshot):
        raise BackupRestoreError("Snapshot must be a real directory, not a reparse point.")
    _assert_no_reparse_points(snapshot)
    manifest_path = snapshot / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupRestoreError(f"Cannot read snapshot manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("format_version") != FORMAT_VERSION:
        raise BackupRestoreError("Unsupported or invalid manifest format_version.")
    if manifest.get("source_layout_version") != 1 or not isinstance(manifest.get("created_at_utc"), str):
        raise BackupRestoreError("Manifest source layout or creation timestamp is invalid.")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise BackupRestoreError("Manifest files must be a non-empty array.")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise BackupRestoreError("Manifest file entry must be an object.")
        relative_text = entry.get("path")
        target = _safe_manifest_path(snapshot, relative_text)
        key = relative_text.casefold()
        if key in seen:
            raise BackupRestoreError(f"Duplicate manifest path: {relative_text}")
        seen.add(key)
        if _is_reparse_point(target) or not target.is_file():
            raise BackupRestoreError(f"Manifest file is missing or unsafe: {relative_text}")
        if not isinstance(entry.get("size"), int) or entry["size"] < 0:
            raise BackupRestoreError(f"Invalid size for {relative_text}")
        if target.stat().st_size != entry["size"]:
            raise BackupRestoreError(f"Size mismatch for {relative_text}")
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or not HASH_RE.fullmatch(expected_hash):
            raise BackupRestoreError(f"Invalid SHA-256 for {relative_text}")
        if _sha256(target) != expected_hash:
            raise BackupRestoreError(f"SHA-256 mismatch for {relative_text}")
    if DATABASE_RELATIVE not in {entry["path"] for entry in entries}:
        raise BackupRestoreError("Manifest does not include DATABASE/catalog.db.")
    actual_files = {
        path.relative_to(snapshot).as_posix().casefold()
        for path in _walk_files(snapshot)
        if path != manifest_path
    }
    if actual_files != seen:
        raise BackupRestoreError("Snapshot contains unlisted files or the manifest omits payload files.")
    _sqlite_integrity(snapshot / DATABASE_RELATIVE)
    return manifest


def create_backup(source_dir: str | Path, destination_dir: str | Path) -> Path:
    source = _resolved(source_dir)
    destination = _resolved(destination_dir)
    if not source.is_dir():
        raise BackupRestoreError(f"Source storage does not exist: {source}")
    if _is_reparse_point(source):
        raise BackupRestoreError("Source storage root must not be a reparse point.")
    marker = _read_storage_marker(source)
    _assert_no_reparse_points(source)
    _assert_separate(source, destination)
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir() or _is_reparse_point(destination):
        raise BackupRestoreError("Backup destination must be a real directory.")
    files = _iter_payload_files(source)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    final_dir = destination / f"hw-catalog-{stamp}"
    final_dir.mkdir(exist_ok=False)
    try:
        _copy_tree_files(source, final_dir, files)
        manifest = _build_manifest(final_dir, marker)
        (final_dir / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        verify_snapshot(final_dir)
        return final_dir
    except Exception:
        # Remove only the uniquely-created incomplete directory from this invocation.
        shutil.rmtree(final_dir, ignore_errors=True)
        raise


def _validate_empty_destination(destination: Path) -> None:
    # Never restore inside an already initialized HW Catalog storage tree.
    current = destination
    while current != current.parent:
        if (current / "DEVICE_INFO.json").is_file():
            raise BackupRestoreError(
                f"Restore destination is inside an initialized storage tree: {current}"
            )
        current = current.parent
    if destination.exists():
        if _is_reparse_point(destination) or not destination.is_dir():
            raise BackupRestoreError("Restore destination must be a real directory.")
        if any(destination.iterdir()):
            raise BackupRestoreError("Restore destination is not empty; refusing to modify it.")
    else:
        destination.mkdir(parents=True, exist_ok=False)
    # Reject reparse-point ancestors to avoid writing through a redirected path.
    current = destination
    while current != current.parent:
        if _is_reparse_point(current):
            raise BackupRestoreError(f"Restore destination path contains a reparse point: {current}")
        current = current.parent


def restore_snapshot(snapshot_dir: str | Path, destination_dir: str | Path) -> Path:
    snapshot = _resolved(snapshot_dir)
    destination = _resolved(destination_dir)
    if not snapshot.is_dir():
        raise BackupRestoreError(f"Snapshot directory does not exist: {snapshot}")
    _assert_no_reparse_points(snapshot)
    manifest = verify_snapshot(snapshot)
    if snapshot == destination or snapshot in destination.parents or destination in snapshot.parents:
        raise BackupRestoreError("Snapshot and restore destination must be separate, non-nested paths.")
    _validate_empty_destination(destination)
    try:
        initialize_storage(destination, label="HW Catalog Restored Storage")
        (destination / ".RESTORE_INCOMPLETE").write_text(
            f"Restore started {_utc_now()}\n", encoding="utf-8"
        )
        for entry in manifest["files"]:
            relative = PurePosixPath(entry["path"])
            source_file = _safe_manifest_path(snapshot, entry["path"])
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
        for entry in manifest["files"]:
            target = destination.joinpath(*PurePosixPath(entry["path"]).parts)
            if target.stat().st_size != entry["size"] or _sha256(target) != entry["sha256"]:
                raise BackupRestoreError(f"Restored file verification failed: {entry['path']}")
        _sqlite_integrity(destination / DATABASE_RELATIVE)
        (destination / ".RESTORE_INCOMPLETE").unlink()
        (destination / "RESTORE_VERIFIED.txt").write_text(
            f"Restored and verified {_utc_now()}\nSnapshot format {FORMAT_VERSION}\n",
            encoding="utf-8",
        )
        return destination
    except Exception as exc:
        # Preserve partial output and make an interrupted/failed restore unmistakable,
        # including failures during storage initialization itself.
        try:
            if destination.is_dir() and not _is_reparse_point(destination):
                incomplete_marker = destination / ".RESTORE_INCOMPLETE"
                if not incomplete_marker.exists():
                    incomplete_marker.write_text(
                        f"Restore failed {_utc_now()}: {type(exc).__name__}: {exc}\\n",
                        encoding="utf-8",
                    )
        except OSError:
            # Do not mask the original restore error if the marker cannot be written.
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe HW Catalog backup and restore.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup", help="Create and verify a new snapshot.")
    backup.add_argument("--source", required=True)
    backup.add_argument("--destination", required=True)
    backup.add_argument("--confirm-backend-stopped", action="store_true", required=True)
    restore = subparsers.add_parser("restore", help="Restore a snapshot into an empty directory.")
    restore.add_argument("--snapshot", required=True)
    restore.add_argument("--destination", required=True)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            result = create_backup(args.source, args.destination)
            print(f"Backup verified: {result}")
        else:
            result = restore_snapshot(args.snapshot, args.destination)
            print(f"Restore verified: {result}")
        return 0
    except (BackupRestoreError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

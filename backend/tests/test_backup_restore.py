import json
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

from app.backup_restore import (
    BackupRestoreError,
    create_backup,
    restore_snapshot,
    verify_snapshot,
)
from app.init_storage import initialize_storage


def make_storage(root: Path) -> dict:
    marker = initialize_storage(root, "Disposable test storage")
    database = root / "DATABASE" / "catalog.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sample(value) VALUES ('round-trip')")
    (root / "MEDIA" / "images" / "sample.txt").write_text("image payload", encoding="utf-8")
    (root / "IMPORTS" / "mainline" / "input.csv").write_text("id,name\n1,test\n", encoding="utf-8")
    (root / "EXPORTS" / "result.txt").write_text("export payload", encoding="utf-8")
    return marker


def test_backup_and_restore_round_trip_with_fresh_storage_identity(tmp_path):
    source = tmp_path / "source"
    source_marker = make_storage(source)
    backup_root = tmp_path / "backups"

    snapshot = create_backup(source, backup_root)
    manifest = verify_snapshot(snapshot)

    assert manifest["format_version"] == 1
    assert "DEVICE_INFO.json" not in json.dumps(manifest)
    assert source_marker["storage_id"] not in json.dumps(manifest)
    assert (snapshot / "DATABASE" / "catalog.db").is_file()
    assert (snapshot / "MEDIA" / "images" / "sample.txt").read_text(encoding="utf-8") == "image payload"

    restored = tmp_path / "restored"
    restore_snapshot(snapshot, restored)

    restored_marker = json.loads((restored / "DEVICE_INFO.json").read_text(encoding="utf-8"))
    assert UUID(restored_marker["storage_id"])
    assert restored_marker["storage_id"] != source_marker["storage_id"]
    assert (restored / "MEDIA" / "images" / "sample.txt").read_text(encoding="utf-8") == "image payload"
    assert (restored / "IMPORTS" / "mainline" / "input.csv").is_file()
    assert (restored / "EXPORTS" / "result.txt").read_text(encoding="utf-8") == "export payload"
    assert (restored / "RESTORE_VERIFIED.txt").is_file()
    with sqlite3.connect(restored / "DATABASE" / "catalog.db") as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("round-trip",)


def test_backup_refuses_nested_destination_without_creating_it(tmp_path):
    source = tmp_path / "source"
    make_storage(source)
    nested = source / "BACKUPS" / "nested"

    with pytest.raises(BackupRestoreError, match="separate"):
        create_backup(source, nested)

    assert not nested.exists()


def test_restore_refuses_non_empty_destination_without_modifying_it(tmp_path):
    source = tmp_path / "source"
    make_storage(source)
    snapshot = create_backup(source, tmp_path / "backups")
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    with pytest.raises(BackupRestoreError, match="not empty"):
        restore_snapshot(snapshot, destination)

    assert sentinel.read_text(encoding="utf-8") == "keep me"


def test_verify_rejects_corrupted_payload(tmp_path):
    source = tmp_path / "source"
    make_storage(source)
    snapshot = create_backup(source, tmp_path / "backups")
    payload = snapshot / "MEDIA" / "images" / "sample.txt"
    payload.write_text("tampered", encoding="utf-8")

    with pytest.raises(BackupRestoreError, match="Size mismatch|SHA-256 mismatch"):
        verify_snapshot(snapshot)


def test_verify_rejects_manifest_path_traversal(tmp_path):
    source = tmp_path / "source"
    make_storage(source)
    snapshot = create_backup(source, tmp_path / "backups")
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../outside.txt"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupRestoreError, match="Unsafe manifest path"):
        verify_snapshot(snapshot)


def test_restore_refuses_destination_that_contains_snapshot(tmp_path):
    source = tmp_path / "source"
    make_storage(source)
    snapshot = create_backup(source, tmp_path / "backups")

    with pytest.raises(BackupRestoreError, match="separate"):
        restore_snapshot(snapshot, snapshot.parent)



def test_verify_rejects_empty_manifest_path(tmp_path):
    source = tmp_path / "source"
    make_storage(source)
    snapshot = create_backup(source, tmp_path / "backups")
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "."
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupRestoreError, match="Unsafe manifest path"):
        verify_snapshot(snapshot)


def test_verify_rejects_missing_payload_file(tmp_path):
    source = tmp_path / "source"
    make_storage(source)
    snapshot = create_backup(source, tmp_path / "backups")
    (snapshot / "MEDIA" / "images" / "sample.txt").unlink()

    with pytest.raises(BackupRestoreError, match="missing or unsafe"):
        verify_snapshot(snapshot)


def test_verify_rejects_sqlite_corruption_even_with_updated_manifest_hash(tmp_path):
    source = tmp_path / "source"
    make_storage(source)
    snapshot = create_backup(source, tmp_path / "backups")
    database = snapshot / "DATABASE" / "catalog.db"
    database.write_bytes(b"not a sqlite database")

    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["path"] == "DATABASE/catalog.db")
    entry["size"] = database.stat().st_size
    import hashlib
    entry["sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupRestoreError, match="SQLite integrity check failed"):
        verify_snapshot(snapshot)



def test_restore_refuses_destination_inside_initialized_storage(tmp_path):
    source = tmp_path / "source"
    make_storage(source)
    snapshot = create_backup(source, tmp_path / "backups")
    active_storage = tmp_path / "active-storage"
    initialize_storage(active_storage)
    destination = active_storage / "restore-target"

    with pytest.raises(BackupRestoreError, match="inside an initialized storage tree"):
        restore_snapshot(snapshot, destination)

    assert not destination.exists()



def test_restore_marks_destination_incomplete_if_storage_initialization_fails(tmp_path, monkeypatch):
    import app.backup_restore as backup_restore

    source = tmp_path / "source"
    make_storage(source)
    snapshot = create_backup(source, tmp_path / "backups")
    destination = tmp_path / "failed-restore"

    def fail_during_initialization(path, label):
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / "partial.txt").write_text("partial", encoding="utf-8")
        raise OSError("simulated initialization failure")

    monkeypatch.setattr(backup_restore, "initialize_storage", fail_during_initialization)

    with pytest.raises(OSError, match="simulated initialization failure"):
        restore_snapshot(snapshot, destination)

    marker = destination / ".RESTORE_INCOMPLETE"
    assert marker.is_file()
    assert "simulated initialization failure" in marker.read_text(encoding="utf-8")
    assert (destination / "partial.txt").read_text(encoding="utf-8") == "partial"

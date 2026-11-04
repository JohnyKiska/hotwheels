import json
from pathlib import Path
from uuid import UUID

import pytest

from app.init_storage import STORAGE_DIRECTORIES, initialize_storage
from app.storage import resolve_database_url


def test_initialize_storage_creates_layout_and_device_marker(tmp_path):
    root = tmp_path / "HW-CATALOG"

    marker = initialize_storage(root, "Development HDD")

    assert marker["layout_version"] == 1
    UUID(marker["storage_id"])
    assert marker["label"] == "Development HDD"
    assert marker["created_at_utc"].endswith("Z")
    assert (root / "DEVICE_INFO.json").is_file()
    assert all((root / relative_dir).is_dir() for relative_dir in STORAGE_DIRECTORIES)

    saved_marker = json.loads((root / "DEVICE_INFO.json").read_text(encoding="utf-8"))
    assert saved_marker == marker


def test_initialized_storage_is_accepted_by_database_resolver(tmp_path, monkeypatch):
    root = tmp_path / "HW-CATALOG"
    initialize_storage(root)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HW_CATALOG_DATA_DIR", str(root))

    url = resolve_database_url()

    assert url.endswith("DATABASE/catalog.db")


def test_initialize_storage_refuses_non_empty_directory_without_changes(tmp_path):
    root = tmp_path / "HW-CATALOG"
    root.mkdir()
    existing_file = root / "keep.txt"
    existing_file.write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        initialize_storage(root)

    assert existing_file.read_text(encoding="utf-8") == "do not overwrite"
    assert not (root / "DEVICE_INFO.json").exists()


def test_initialize_storage_requires_absolute_path():
    with pytest.raises(ValueError, match="absolute"):
        initialize_storage("relative/HW-CATALOG")


def test_initialize_storage_rejects_empty_label(tmp_path):
    with pytest.raises(ValueError, match="label"):
        initialize_storage(tmp_path / "HW-CATALOG", "   ")

    assert not (tmp_path / "HW-CATALOG").exists()

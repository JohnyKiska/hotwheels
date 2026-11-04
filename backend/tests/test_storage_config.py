import json
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.storage import (
    DEFAULT_DATABASE_PATH,
    StorageConfigurationError,
    resolve_database_url,
    sqlite_url_for_path,
)


def _initialize_external_storage(root: Path) -> None:
    root.mkdir()
    (root / "DATABASE").mkdir()
    (root / "DEVICE_INFO.json").write_text(
        json.dumps({
            "storage_id": "d5b6f93e-5d1d-4e68-9d14-63e30a5d7f8c",
            "layout_version": 1,
        }),
        encoding="utf-8",
    )


def test_default_database_path_preserves_legacy_development_location(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HW_CATALOG_DATA_DIR", raising=False)

    assert resolve_database_url() == sqlite_url_for_path(DEFAULT_DATABASE_PATH)
    assert DEFAULT_DATABASE_PATH.as_posix().endswith("backend/hotwheels.db")


def test_external_storage_selects_catalog_database(tmp_path, monkeypatch):
    root = tmp_path / "HW-CATALOG"
    _initialize_external_storage(root)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HW_CATALOG_DATA_DIR", str(root))

    url = resolve_database_url()

    assert url.startswith("sqlite:///")
    assert Path(make_url(url).database) == root / "DATABASE" / "catalog.db"


def test_missing_external_storage_fails_closed_without_creating_directories(
    tmp_path, monkeypatch
):
    root = tmp_path / "disconnected-drive" / "HW-CATALOG"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HW_CATALOG_DATA_DIR", str(root))

    with pytest.raises(StorageConfigurationError, match="does not exist"):
        resolve_database_url()

    assert not root.exists()


def test_external_storage_requires_device_marker(tmp_path, monkeypatch):
    root = tmp_path / "HW-CATALOG"
    root.mkdir()
    (root / "DATABASE").mkdir()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HW_CATALOG_DATA_DIR", str(root))

    with pytest.raises(StorageConfigurationError, match="marker is missing"):
        resolve_database_url()


def test_external_storage_rejects_invalid_device_identity(tmp_path, monkeypatch):
    root = tmp_path / "HW-CATALOG"
    _initialize_external_storage(root)
    marker = root / "DEVICE_INFO.json"
    marker.write_text(
        json.dumps({"storage_id": "not-a-uuid", "layout_version": 1}),
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HW_CATALOG_DATA_DIR", str(root))

    with pytest.raises(StorageConfigurationError, match="valid UUID"):
        resolve_database_url()


def test_external_storage_requires_existing_database_directory(tmp_path, monkeypatch):
    root = tmp_path / "HW-CATALOG"
    root.mkdir()
    (root / "DEVICE_INFO.json").write_text(
        json.dumps({
            "storage_id": "d5b6f93e-5d1d-4e68-9d14-63e30a5d7f8c",
            "layout_version": 1,
        }),
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HW_CATALOG_DATA_DIR", str(root))

    with pytest.raises(StorageConfigurationError, match="database directory is missing"):
        resolve_database_url()

    assert not (root / "DATABASE").exists()


def test_explicit_database_url_takes_precedence_over_external_storage(
    tmp_path, monkeypatch
):
    explicit_url = "sqlite:///controlled-test.db"
    monkeypatch.setenv("DATABASE_URL", explicit_url)
    monkeypatch.setenv("HW_CATALOG_DATA_DIR", str(tmp_path / "missing-drive"))

    assert resolve_database_url() == explicit_url


def test_sqlite_url_supports_windows_drive_letter_paths():
    url = sqlite_url_for_path(r"H:\HW-CATALOG\DATABASE\catalog.db")

    assert url.startswith("sqlite:///")
    assert "HW-CATALOG" in url
    assert "catalog.db" in url

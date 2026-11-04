"""Centralized database location and external-storage validation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy.engine import URL

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "hotwheels.db"
DATABASE_RELATIVE_PATH = Path("DATABASE") / "catalog.db"
DEVICE_MARKER_NAME = "DEVICE_INFO.json"
SUPPORTED_LAYOUT_VERSION = 1


class StorageConfigurationError(RuntimeError):
    """Raised when configured catalog storage is missing or invalid."""


def sqlite_url_for_path(database_path: str | Path) -> str:
    """Build a SQLite URL safely, including Windows drive-letter paths."""
    return URL.create("sqlite", database=str(database_path)).render_as_string(
        hide_password=False
    )


def _validate_external_storage(data_dir: str | Path) -> Path:
    root = Path(data_dir).expanduser()
    if not root.is_dir():
        raise StorageConfigurationError(
            f"Configured HW_CATALOG_DATA_DIR does not exist or is not a directory: {root}"
        )

    marker_path = root / DEVICE_MARKER_NAME
    if not marker_path.is_file():
        raise StorageConfigurationError(
            f"External catalog storage marker is missing: {marker_path}. "
            "Initialize the storage before starting the backend."
        )

    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageConfigurationError(
            f"Cannot read external catalog storage marker: {marker_path}"
        ) from exc

    if not isinstance(marker, dict):
        raise StorageConfigurationError("DEVICE_INFO.json must contain a JSON object.")

    storage_id = marker.get("storage_id")
    try:
        UUID(str(storage_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise StorageConfigurationError(
            "DEVICE_INFO.json must contain a valid UUID in 'storage_id'."
        ) from exc

    if marker.get("layout_version") != SUPPORTED_LAYOUT_VERSION:
        raise StorageConfigurationError(
            "Unsupported or missing storage layout_version in DEVICE_INFO.json."
        )

    database_dir = root / "DATABASE"
    if not database_dir.is_dir():
        raise StorageConfigurationError(
            f"External catalog database directory is missing: {database_dir}. "
            "The backend will not create it automatically."
        )

    return database_dir / "catalog.db"


def resolve_database_url(default_url: str | None = None) -> str:
    """Resolve one database URL for both the app and Alembic.

    DATABASE_URL is an explicit override for tests and controlled deployments.
    HW_CATALOG_DATA_DIR selects an initialized external storage device.
    Otherwise, development keeps using backend/hotwheels.db.
    """
    explicit_url = os.environ.get("DATABASE_URL")
    if explicit_url:
        return explicit_url

    data_dir = os.environ.get("HW_CATALOG_DATA_DIR")
    if data_dir:
        return sqlite_url_for_path(_validate_external_storage(data_dir))

    if default_url:
        return default_url

    return sqlite_url_for_path(DEFAULT_DATABASE_PATH)

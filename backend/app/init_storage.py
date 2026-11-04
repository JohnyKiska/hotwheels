"""Create an initialized, portable HW Catalog storage directory."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

STORAGE_DIRECTORIES = (
    Path("DATABASE"),
    Path("MEDIA") / "images",
    Path("MEDIA") / "thumbnails",
    Path("IMPORTS") / "mainline",
    Path("IMPORTS") / "premium",
    Path("IMPORTS") / "allhw",
    Path("EXPORTS"),
    Path("BACKUPS") / "daily",
    Path("BACKUPS") / "manual",
)


def initialize_storage(data_dir: str | Path, label: str = "HW Catalog Storage") -> dict:
    """Create a new storage layout without overwriting any existing contents."""
    root = Path(data_dir).expanduser()
    if not root.is_absolute():
        raise ValueError("Storage path must be absolute to avoid initializing the wrong location.")
    if not label.strip():
        raise ValueError("Storage label must not be empty.")

    if root.exists():
        if not root.is_dir():
            raise ValueError(f"Storage path exists and is not a directory: {root}")
        if any(root.iterdir()):
            raise FileExistsError(
                f"Storage directory is not empty; refusing to modify it: {root}"
            )
    else:
        root.mkdir(parents=True)

    for relative_dir in STORAGE_DIRECTORIES:
        (root / relative_dir).mkdir(parents=True, exist_ok=True)

    marker = {
        "storage_id": str(uuid4()),
        "layout_version": 1,
        "label": label.strip(),
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    marker_path = root / "DEVICE_INFO.json"
    with marker_path.open("x", encoding="utf-8") as marker_file:
        json.dump(marker, marker_file, ensure_ascii=False, indent=2)
        marker_file.write("\n")

    return marker


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize a new HW Catalog storage directory."
    )
    parser.add_argument(
        "path",
        help=r"Absolute path to the new storage root, e.g. H:\HW-CATALOG",
    )
    parser.add_argument(
        "--label",
        default="HW Catalog Storage",
        help="Human-readable storage label.",
    )
    args = parser.parse_args()

    try:
        marker = initialize_storage(args.path, args.label)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"HW Catalog storage initialized: {Path(args.path).expanduser()}")
    print(f"Storage ID: {marker['storage_id']}")
    print("No database was created or catalog data imported.")


if __name__ == "__main__":
    main()

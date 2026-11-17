"""Filesystem-backed storage for original media and generated thumbnails."""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageOps, UnidentifiedImageError

from .storage import BACKEND_DIR

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
THUMBNAIL_SIZE = (640, 640)
ALLOWED_FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}


class StoredImage(NamedTuple):
    storage_key: str
    thumbnail_key: str
    checksum_sha256: str
    mime_type: str
    width: int
    height: int
    byte_size: int


class InvalidImage(ValueError):
    """The uploaded bytes are not an allowed, safely decodable image."""


def media_root() -> Path:
    """Resolve media storage independently from the database connection."""
    configured = os.environ.get("HW_CATALOG_MEDIA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    data_dir = os.environ.get("HW_CATALOG_DATA_DIR")
    if data_dir:
        return (Path(data_dir).expanduser() / "MEDIA").resolve()
    return (BACKEND_DIR / "media").resolve()


def _atomic_write(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".upload-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def store_image(data: bytes) -> StoredImage:
    if not data:
        raise InvalidImage("The uploaded file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidImage(f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit.")

    try:
        with Image.open(io.BytesIO(data)) as probe:
            image_format = (probe.format or "").upper()
            if image_format not in ALLOWED_FORMATS:
                raise InvalidImage("Only JPEG, PNG and WEBP images are accepted.")
            if getattr(probe, "is_animated", False):
                raise InvalidImage("Animated images are not accepted.")
            width, height = probe.size
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                raise InvalidImage("Image dimensions exceed the allowed limit.")
            probe.verify()
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            width, height = image.size
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            thumb = image.copy()
            thumb.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            thumb_buffer = io.BytesIO()
            thumb.save(thumb_buffer, format="WEBP", quality=82, method=6)
    except InvalidImage:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
        raise InvalidImage("The uploaded file is not a valid supported image.") from exc

    extension, mime_type = ALLOWED_FORMATS[image_format]
    checksum = hashlib.sha256(data).hexdigest()
    relative = Path(checksum[:2])
    original_key = (Path("images") / relative / f"{checksum}.{extension}").as_posix()
    thumbnail_key = (Path("thumbnails") / relative / f"{checksum}.webp").as_posix()
    root = media_root()
    original_path = (root / original_key).resolve()
    thumbnail_path = (root / thumbnail_key).resolve()
    if root not in original_path.parents or root not in thumbnail_path.parents:
        raise InvalidImage("Generated storage path is invalid.")

    _atomic_write(original_path, data)
    try:
        _atomic_write(thumbnail_path, thumb_buffer.getvalue())
    except Exception:
        try:
            original_path.unlink()
        except FileNotFoundError:
            pass
        raise

    return StoredImage(
        original_key, thumbnail_key, checksum, mime_type, width, height, len(data)
    )


def resolve_media_file(storage_key: str) -> Path:
    """Resolve a DB storage key and reject absolute paths or traversal."""
    candidate = Path(storage_key)
    if candidate.is_absolute() or not candidate.parts or any(part in ("", ".", "..") for part in candidate.parts):
        raise ValueError("Unsafe media storage key.")
    root = media_root()
    resolved = (root / candidate).resolve()
    if root not in resolved.parents:
        raise ValueError("Media path escapes the configured storage root.")
    return resolved


def resolve_thumbnail(checksum_sha256: str) -> Path:
    if len(checksum_sha256) != 64 or any(c not in "0123456789abcdef" for c in checksum_sha256.lower()):
        raise ValueError("Invalid media checksum.")
    return resolve_media_file(f"thumbnails/{checksum_sha256[:2]}/{checksum_sha256.lower()}.webp")


def remove_stored_image(storage_key: str, checksum_sha256: str) -> None:
    for path in (resolve_media_file(storage_key), resolve_thumbnail(checksum_sha256)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

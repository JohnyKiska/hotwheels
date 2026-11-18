from app.media_storage import media_root


def test_external_media_storage_fails_closed_when_drive_is_missing(tmp_path, monkeypatch):
    missing = tmp_path / "disconnected" / "HW-CATALOG"
    monkeypatch.delenv("HW_CATALOG_MEDIA_DIR", raising=False)
    monkeypatch.setenv("HW_CATALOG_DATA_DIR", str(missing))

    try:
        media_root()
    except RuntimeError as exc:
        assert "refusing to create a fallback directory" in str(exc)
    else:
        raise AssertionError("Missing external storage must fail closed.")

    assert not missing.exists()

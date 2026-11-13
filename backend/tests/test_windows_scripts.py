from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_SCRIPTS = REPO_ROOT / "scripts" / "windows"


def test_windows_start_script_checks_external_storage_and_runs_migrations():
    script = (WINDOWS_SCRIPTS / "start-hw-catalog.ps1").read_text(encoding="utf-8")
    assert "DEVICE_INFO.json" in script
    assert "layout_version" in script
    assert "HW_CATALOG_DATA_DIR" in script
    assert "DATABASE_URL" in script
    assert "alembic upgrade head" in script
    assert "app.main:app" in script
    assert "127.0.0.1" in script


def test_windows_stop_script_waits_for_graceful_ctrl_c_and_never_force_kills():
    script = (WINDOWS_SCRIPTS / "stop-hw-catalog.ps1").read_text(encoding="utf-8")
    assert "Ctrl+C" in script
    assert "TimeoutSeconds" in script
    assert "Get-CimInstance" in script
    assert "Принудительно завершать процесс он НЕ будет" in script
    assert "Stop-Process -Force" not in script
    assert "taskkill" not in script.lower()

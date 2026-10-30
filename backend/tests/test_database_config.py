import os
from pathlib import Path
import subprocess
import sys


def test_database_url_environment_variable_configures_application_engine(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "configured.db"
    configured_url = f"sqlite:///{database_path}"
    env = {**os.environ, "DATABASE_URL": configured_url}

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.db import DATABASE_URL, engine; "
            "print(DATABASE_URL); print(engine.url)",
        ],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert configured_url in result.stdout
    assert str(database_path) in result.stdout

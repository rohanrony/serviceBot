"""Regression coverage for test environment initialization."""

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_conftest_preserves_explicit_runtime_paths(tmp_path):
    """The test-specific log path wins over inherited local developer settings."""
    log_file = tmp_path / "isolated.log"
    db_url = "postgresql://localhost/isolated_voice_service_test"
    env = os.environ | {
        "LOG_FILE": "/Users/rohanroy/Coding/voiceService/logs/local_server.log",
        "TEST_LOG_FILE": str(log_file),
        "TEST_DATABASE_URL": db_url,
        "TEST_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; import tests.conftest; print(os.environ['LOG_FILE']); print(os.environ['DATABASE_URL'])",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[-2:] == [str(log_file), db_url]

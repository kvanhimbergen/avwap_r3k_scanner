from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

if os.getenv("AVWAP_SKIP_COLLECT_ONLY_CHECK") == "1":
    pytest.skip("Avoid recursive pytest invocation during collect-only checks.", allow_module_level=True)


def test_pytest_collect_only_imports_requests() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["AVWAP_SKIP_COLLECT_ONLY_CHECK"] = "1"
    # Ensure determinism in the subprocess: plugin autoload can introduce
    # environment-sensitive import side effects during collection.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "pytest --collect-only failed.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


"""Run all tests with: python tests/run_tests.py

This is the single source of truth for the test entrypoint in CI and operator workflows.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def _pytest_available() -> bool:
    return importlib.util.find_spec("pytest") is not None


def iter_test_files(root: Path | None = None) -> list[Path]:
    if root is None:
        root = Path(__file__).resolve().parents[1]
    tests_root = root / "tests"
    return sorted(tests_root.glob("test_*.py"), key=lambda path: path.name)


def main() -> int:
    if not _pytest_available():
        print("FAIL: pytest is not installed.")
        print("Install it with: pip install -r requirements-dev.txt")
        print("Or: pip install pytest")
        return 1

    root = Path(__file__).resolve().parents[1]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)

    tests = iter_test_files(root)

    any_fail = False
    for test_path in tests:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path)],
            env=env,
        )
        if result.returncode == 0:
            print(f"PASS: {test_path}")
        else:
            print(f"FAIL: {test_path}")
            any_fail = True

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

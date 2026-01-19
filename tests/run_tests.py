
"""Run all tests with: python tests/run_tests.py"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
import os


def _pytest_available() -> bool:
    return importlib.util.find_spec("pytest") is not None


def main() -> int:
    if not _pytest_available():
        print("FAIL: pytest is not installed.")
        print("Install it with: pip install -r requirements.txt")
        print("Or: pip install pytest")
        return 1

    root = Path(__file__).resolve().parents[1]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)

    tests = [
        root / "tests" / "test_universe.py",
        root / "tests" / "test_no_lookahead.py",
        root / "tests" / "test_determinism.py",
        root / "tests" / "test_backtest_observability.py",
        root / "tests" / "test_backtest_sizing.py",
        root / "tests" / "test_parity_scan_backtest.py",
        root / "tests" / "test_sweep_runner.py",
    ]

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

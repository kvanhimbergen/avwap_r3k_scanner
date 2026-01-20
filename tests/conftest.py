"""
Pytest configuration.

Purpose:
- Ensure the repository root is on sys.path during test collection and execution.

Why:
- Some environments (notably macOS + certain pytest invocation patterns) can collect tests
  with a sys.path that does not include the repo root, causing ModuleNotFoundError for
  root-level modules like `config.py` and `backtest_engine.py`.

This file is test-harness only. It must not alter production behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

repo_root_str = str(REPO_ROOT)
if sys.path[0] != repo_root_str:
    if repo_root_str in sys.path:
        sys.path.remove(repo_root_str)
    sys.path.insert(0, repo_root_str)

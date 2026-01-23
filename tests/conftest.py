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

import importlib.abc
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEBUG_IMPORTS = os.getenv("AVWAP_DEBUG_IMPORTS") == "1"
LAST_COLLECTED_MODULE: str | None = None


def _log_requests_state(context: str) -> None:
    if not DEBUG_IMPORTS:
        return
    requests_mod = sys.modules.get("requests")
    requests_file = getattr(requests_mod, "__file__", None)
    requests_spec = getattr(requests_mod, "__spec__", None)
    has_session = hasattr(requests_mod, "Session") if requests_mod else False
    print(
        "\n".join(
            [
                f"[avwap-debug] context={context}",
                f"[avwap-debug] sys.executable={sys.executable}",
                f"[avwap-debug] sys.path[:8]={sys.path[:8]}",
                f"[avwap-debug] last_collected_module={LAST_COLLECTED_MODULE}",
                f"[avwap-debug] requests_module={requests_mod!r}",
                f"[avwap-debug] requests.__file__={requests_file}",
                f"[avwap-debug] requests.__spec__={requests_spec}",
                f"[avwap-debug] requests_has_Session={has_session}",
            ]
        ),
        file=sys.stderr,
    )


class _RequestsImportLogger(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object | None, target: object | None = None):
        if fullname == "requests":
            _log_requests_state("before import requests")
        return None


repo_root_str = str(REPO_ROOT)
if repo_root_str not in sys.path:
    insert_at = 1 if len(sys.path) > 1 else 0
    sys.path.insert(insert_at, repo_root_str)

if DEBUG_IMPORTS:
    sys.meta_path.insert(0, _RequestsImportLogger())
    _log_requests_state("pytest startup")


def pytest_pycollect_makemodule(module_path, parent):  # type: ignore[override]
    global LAST_COLLECTED_MODULE
    LAST_COLLECTED_MODULE = str(module_path)
    if DEBUG_IMPORTS:
        print(f"[avwap-debug] collecting={LAST_COLLECTED_MODULE}", file=sys.stderr)

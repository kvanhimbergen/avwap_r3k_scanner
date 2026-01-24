from __future__ import annotations

import re
from pathlib import Path


def test_execution_v2_has_no_analytics_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    execution_dir = root / "execution_v2"
    pattern = re.compile(r"^(from|import)\s+analytics(\.|\\b)")
    for path in execution_dir.rglob("*.py"):
        for line in path.read_text().splitlines():
            if pattern.search(line.strip()):
                raise AssertionError(f"analytics import detected in {path}: {line}")

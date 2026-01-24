from __future__ import annotations

from pathlib import Path


def test_execution_v2_has_no_schwab_readonly_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    execution_dir = root / "execution_v2"
    for path in execution_dir.rglob("*.py"):
        content = path.read_text()
        assert "schwab_readonly" not in content

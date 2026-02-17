from __future__ import annotations

from pathlib import Path

import pytest


def _snapshot(paths: list[Path]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for path in paths:
        stat = path.stat()
        out[str(path)] = (int(stat.st_size), int(stat.st_mtime_ns))
    return out


def test_dashboard_does_not_mutate_ledger_or_state(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from analytics_platform.backend.app import create_app
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    source_files = sorted((analytics_settings.repo_root / "ledger").glob("**/*.jsonl"))
    source_files += sorted((analytics_settings.repo_root / "state").glob("*.json"))

    before = _snapshot(source_files)
    build_readmodels(analytics_settings)

    app = create_app(settings=analytics_settings)
    client = TestClient(app)
    assert client.get("/api/v1/overview").status_code == 200
    assert client.get("/api/v1/freshness").status_code == 200
    assert client.get("/api/v1/decisions/timeseries").status_code == 200

    after = _snapshot(source_files)
    assert before == after

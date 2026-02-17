from __future__ import annotations

import pytest

def test_api_contracts(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from analytics_platform.backend.app import create_app
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)
    app = create_app(settings=analytics_settings)
    client = TestClient(app)

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert "data" in health.json()

    overview = client.get("/api/v1/overview")
    assert overview.status_code == 200
    assert "totals" in overview.json()["data"]

    compare = client.get("/api/v1/strategies/compare")
    assert compare.status_code == 200
    assert "intent_compare" in compare.json()["data"]

    signals = client.get("/api/v1/signals/s2")
    assert signals.status_code == 200
    assert signals.json()["data"]["count"] == 1

    run_list = client.get("/api/v1/backtests/runs")
    assert run_list.status_code == 200
    runs = run_list.json()["data"]["runs"]
    assert len(runs) == 1

    run_id = runs[0]["run_id"]
    run_detail = client.get(f"/api/v1/backtests/runs/{run_id}")
    assert run_detail.status_code == 200
    assert "metrics" in run_detail.json()["data"]

    export = client.get("/api/v1/exports/strategy_signals.csv")
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]

from __future__ import annotations

import pytest


def _make_client(analytics_settings):
    """Shared boilerplate: importorskip, build readmodels, return TestClient."""
    pytest.importorskip("duckdb")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from analytics_platform.backend.app import create_app
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)
    app = create_app(settings=analytics_settings)
    return TestClient(app)


def test_raec_dashboard(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/raec/dashboard")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "by_strategy" in data
    assert len(data["by_strategy"]) >= 1
    assert any(s["strategy_id"] == "RAEC_401K_V3" for s in data["by_strategy"])
    assert "regime_history" in data
    assert "allocation_snapshots" in data


def test_raec_dashboard_filter_strategy(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/raec/dashboard?strategy_id=RAEC_401K_V3")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Only V3 data should be present
    for entry in data["by_strategy"]:
        assert entry["strategy_id"] == "RAEC_401K_V3"


def test_journal(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/journal")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "rows" in data
    assert "count" in data
    # Fixture has 3 RAEC intents + 2 decision intents = 5
    assert data["count"] >= 3


def test_journal_filter_symbol(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/journal?symbol=TQQQ")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] >= 1
    for row in data["rows"]:
        assert row["symbol"] == "TQQQ"


def test_readiness(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/raec/readiness")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "strategies" in data


def test_pnl(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/pnl")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "by_strategy" in data


def test_raec_exports(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/exports/raec_intents.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]


def test_strategies_compare_includes_raec(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/strategies/compare")
    assert resp.status_code == 200
    assert "intent_compare" in resp.json()["data"]

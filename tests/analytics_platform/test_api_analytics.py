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


def test_slippage_dashboard(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/execution/slippage")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "summary" in data
    assert "mean_bps" in data["summary"]
    assert "total" in data["summary"]
    assert "by_bucket" in data
    assert len(data["by_bucket"]) >= 1


def test_slippage_filter_strategy(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/execution/slippage?strategy_id=S1_AVWAP_CORE")
    assert resp.status_code == 200
    data = resp.json()["data"]
    symbols = {row["symbol"] for row in data["by_symbol"]}
    assert "TQQQ" not in symbols


def test_trade_analytics(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/analytics/trades")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "per_strategy" in data
    assert len(data["per_strategy"]) >= 1


def test_trade_analytics_daily_frequency(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/analytics/trades")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "daily_frequency" in data
    assert len(data["daily_frequency"]) >= 1


def test_slippage_export(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/exports/execution_slippage.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]


def test_portfolio_snapshots_export(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/exports/portfolio_snapshots.csv")
    assert resp.status_code == 200

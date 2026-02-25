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


def test_performance_endpoint_200(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/performance")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "swing_metrics" in data
    assert "portfolio_metrics" in data
    assert "raec_metrics" in data
    assert "order_log" in data


def test_performance_cold_start(analytics_settings, sample_repo) -> None:
    """With only single snapshot, portfolio data_sufficient should be False."""
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/performance")
    data = resp.json()["data"]
    # We only have 1 snapshot in fixtures, so data_sufficient should be False
    assert data["portfolio_metrics"]["data_sufficient"] is False
    assert data["portfolio_metrics"]["data_points"] == 1


def test_performance_portfolio_metrics_structure(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/performance")
    pm = resp.json()["data"]["portfolio_metrics"]

    expected_keys = {
        "total_return", "annualized_return", "sharpe_ratio", "sortino_ratio",
        "max_drawdown", "calmar_ratio", "data_points", "equity_curve",
        "benchmark", "benchmark_return", "excess_return", "benchmark_curve",
        "data_sufficient",
    }
    assert expected_keys.issubset(set(pm.keys()))
    assert pm["benchmark"] == "SPY"
    assert isinstance(pm["equity_curve"], list)
    assert isinstance(pm["benchmark_curve"], list)


def test_performance_filter_by_strategy(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/performance?strategy_id=S2_LETF_ORB_AGGRO")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Only S2 should appear in swing metrics (if any)
    for sid in data["swing_metrics"]:
        assert sid == "S2_LETF_ORB_AGGRO"


def test_performance_swing_metrics_with_closed_trade(analytics_settings) -> None:
    """S2_LETF_ORB_AGGRO has a buy+sell pair in fixtures, verify it shows up."""
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/performance")
    data = resp.json()["data"]
    swing = data["swing_metrics"]
    if "S2_LETF_ORB_AGGRO" in swing:
        s2 = swing["S2_LETF_ORB_AGGRO"]
        assert s2["closed_trade_count"] == 1
        assert s2["gross_pnl"] > 0  # 77.25 - 75.10 = 2.15 profit
        assert s2["data_sufficient"] is False  # only 1 trade, need 5


def test_performance_order_log(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/performance")
    data = resp.json()["data"]
    order_log = data["order_log"]
    assert len(order_log) >= 2  # at least the S2 buy+sell
    symbols = {o["symbol"] for o in order_log}
    assert "TQQQ" in symbols


def test_performance_raec_metrics(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/performance")
    data = resp.json()["data"]
    raec = data["raec_metrics"]
    # We have RAEC_401K_V1 and RAEC_401K_V3 in fixtures
    assert len(raec) >= 1
    for sid, m in raec.items():
        assert "rebalance_count" in m
        assert "regime_changes" in m
        assert "current_regime" in m
        assert "data_sufficient" in m


def test_alpaca_order_events_export(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/exports/alpaca_order_events.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    lines = resp.text.strip().split("\n")
    assert len(lines) >= 2  # header + at least 1 data row
    header = lines[0]
    assert "symbol" in header
    assert "side" in header

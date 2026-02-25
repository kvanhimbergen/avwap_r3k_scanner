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


def test_schwab_overview_returns_200(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/overview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "latest_account" in data
    assert "balance_history" in data
    assert "positions" in data
    assert "orders" in data
    assert "latest_reconciliation" in data


def test_schwab_overview_latest_account(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/overview")
    data = resp.json()["data"]

    acct = data["latest_account"]
    assert acct is not None
    assert acct["ny_date"] == "2026-02-10"
    assert acct["cash"] == pytest.approx(5000.0)
    assert acct["market_value"] == pytest.approx(20922.83)
    assert acct["total_value"] == pytest.approx(25922.83)


def test_schwab_overview_positions(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/overview")
    data = resp.json()["data"]

    positions = data["positions"]
    assert len(positions) == 3
    # Sorted by market_value DESC: TQQQ(7725) > BIL(7997.83) > SOXL(5200)
    # Actually: BIL=7997.83, TQQQ=7725, SOXL=5200
    symbols = [p["symbol"] for p in positions]
    assert "TQQQ" in symbols
    assert "SOXL" in symbols
    assert "BIL" in symbols

    # Check weight_pct sums to 100
    total_weight = sum(p["weight_pct"] for p in positions)
    assert total_weight == pytest.approx(100.0, abs=0.1)


def test_schwab_overview_orders(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/overview")
    data = resp.json()["data"]

    orders = data["orders"]
    assert len(orders) == 1
    assert orders[0]["symbol"] == "TQQQ"
    assert orders[0]["side"] == "BUY"
    assert orders[0]["status"] == "FILLED"


def test_schwab_overview_reconciliation(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/overview")
    data = resp.json()["data"]

    recon = data["latest_reconciliation"]
    assert recon is not None
    assert recon["ny_date"] == "2026-02-10"
    assert recon["broker_position_count"] == 3
    assert recon["drift_intent_count"] == 0
    assert recon["drift_symbol_count"] == 0

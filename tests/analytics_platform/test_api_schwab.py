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
    assert acct["ny_date"] == "2026-02-11"
    assert acct["cash"] == pytest.approx(5000.0)
    assert acct["market_value"] == pytest.approx(21500.0)
    assert acct["total_value"] == pytest.approx(26500.0)


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

    # Check weight_pct sums to ~100
    total_weight = sum(p["weight_pct"] for p in positions)
    assert total_weight == pytest.approx(100.0, abs=0.5)


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


# ── Trade instructions endpoint ──────────────────────────────────


def test_trade_instructions_returns_200(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/trade-instructions")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "days" in data
    assert "total_value" in data
    assert "threshold_dollars" in data
    assert "threshold_pct" in data


def test_trade_instructions_has_v3_intents(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/trade-instructions")
    data = resp.json()["data"]

    # Should have at least one day with V3 intents from the fixture
    assert len(data["days"]) >= 1
    day = data["days"][0]
    assert day["ny_date"] == "2026-02-10"
    assert len(day["intents"]) == 3  # TQQQ BUY, SOXL BUY, SPY SELL

    symbols = {i["symbol"] for i in day["intents"]}
    assert symbols == {"TQQQ", "SOXL", "SPY"}

    # All intents should have dollar_amount and actionable fields
    for intent in day["intents"]:
        assert "dollar_amount" in intent
        assert "actionable" in intent
        assert intent["strategy_id"] == "RAEC_401K_V3"


def test_trade_instructions_threshold_scales_with_portfolio(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/trade-instructions")
    data = resp.json()["data"]

    # Portfolio total is $26,500.00 (latest day) → 0.5% = $132.50 → threshold = max($250, $132.50) = $250
    assert data["total_value"] == pytest.approx(26500.0)
    assert data["threshold_dollars"] == pytest.approx(250.0)
    assert data["threshold_pct"] == 0.5


def test_trade_instructions_dollar_amounts(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/trade-instructions")
    data = resp.json()["data"]

    day = data["days"][0]
    # TQQQ BUY delta_pct=35.0 → $26,500.00 * 0.35 = $9,275.00
    tqqq = next(i for i in day["intents"] if i["symbol"] == "TQQQ")
    assert tqqq["dollar_amount"] == pytest.approx(26500.0 * 35.0 / 100, abs=1.0)
    assert tqqq["actionable"] is True  # well above $250 threshold


def test_trade_instructions_events(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/trade-instructions")
    data = resp.json()["data"]

    day = data["days"][0]
    # Should have the V3 rebalance event
    assert len(day["events"]) >= 1
    v3_event = next((e for e in day["events"] if e["strategy_id"] == "RAEC_401K_V3"), None)
    assert v3_event is not None
    assert v3_event["regime"] == "RISK_ON"
    assert v3_event["should_rebalance"] is True


# ── Performance endpoint ─────────────────────────────────────────


def test_schwab_performance_returns_200(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/performance")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "series" in data
    assert "metrics" in data
    assert "data_sufficient" in data


def test_schwab_performance_data_sufficient(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/performance")
    data = resp.json()["data"]
    # We have 2 snapshot dates (2026-02-10, 2026-02-11)
    assert data["data_sufficient"] is True
    assert len(data["series"]) == 2


def test_schwab_performance_series_values(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/performance")
    data = resp.json()["data"]

    series = data["series"]
    # First point should be 0% (baseline)
    assert series[0]["date"] == "2026-02-10"
    assert series[0]["portfolio"] == pytest.approx(0.0)
    assert series[0]["spy"] == pytest.approx(0.0)
    assert series[0]["vti"] == pytest.approx(0.0)

    # Second point: portfolio went from 25922.83 to 26500 = +2.23%
    assert series[1]["date"] == "2026-02-11"
    expected_port = (26500 - 25922.83) / 25922.83 * 100
    assert series[1]["portfolio"] == pytest.approx(expected_port, abs=0.1)

    # SPY went from 500 to 505 = +1.0%
    assert series[1]["spy"] == pytest.approx(1.0, abs=0.01)
    # VTI went from 250 to 253 = +1.2%
    assert series[1]["vti"] == pytest.approx(1.2, abs=0.01)


def test_schwab_performance_metrics(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/schwab/performance")
    data = resp.json()["data"]

    metrics = data["metrics"]
    assert metrics["start_date"] == "2026-02-10"
    assert metrics["end_date"] == "2026-02-11"
    assert metrics["start_value"] == pytest.approx(25922.83)
    assert metrics["end_value"] == pytest.approx(26500.0)
    assert metrics["portfolio_return"] is not None
    assert metrics["spy_return"] is not None
    assert metrics["vti_return"] is not None
    assert metrics["excess_vs_spy"] is not None
    assert metrics["excess_vs_vti"] is not None


def test_schwab_performance_date_filter(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    # Filter to only 2026-02-11 → only 1 data point → not sufficient
    resp = client.get("/api/v1/schwab/performance?start=2026-02-11")
    data = resp.json()["data"]
    assert data["data_sufficient"] is False

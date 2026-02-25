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

    # WS3: events array must be present with per-event data
    assert "events" in data
    assert isinstance(data["events"], list)
    assert len(data["events"]) >= 1
    ev0 = data["events"][0]
    for field in ("ny_date", "strategy_id", "should_rebalance", "book_id"):
        assert field in ev0, f"missing field {field} in event"


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

    # WS4: V1/V2 appear with book_id ALPACA_PAPER
    v1 = next((s for s in data["strategies"] if s["strategy_id"] == "RAEC_401K_V1"), None)
    assert v1 is not None, "V1 missing from readiness"
    assert v1["book_id"] == "ALPACA_PAPER"
    v2 = next((s for s in data["strategies"] if s["strategy_id"] == "RAEC_401K_V2"), None)
    assert v2 is not None, "V2 missing from readiness"
    assert v2["book_id"] == "ALPACA_PAPER"

    # WS4: by_book grouping
    assert "by_book" in data
    assert "ALPACA_PAPER" in data["by_book"]
    assert "SCHWAB_401K_MANUAL" in data["by_book"]
    alpaca_ids = {s["strategy_id"] for s in data["by_book"]["ALPACA_PAPER"]}
    assert "RAEC_401K_V1" in alpaca_ids
    assert "RAEC_401K_V2" in alpaca_ids
    schwab_ids = {s["strategy_id"] for s in data["by_book"]["SCHWAB_401K_MANUAL"]}
    assert "RAEC_401K_V3" in schwab_ids

    # WS4: computed allocation fields
    assert "has_allocations" in v1
    assert "allocation_count" in v1
    assert "total_weight_pct" in v1


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


def test_strategy_matrix_book_id(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/strategies/matrix")
    assert resp.status_code == 200
    data = resp.json()["data"]
    strategies = data["strategies"]
    assert len(strategies) >= 1
    # Every strategy should have book_id
    for s in strategies:
        assert "book_id" in s, f"missing book_id on {s['strategy_id']}"
    # V3 (RAEC) should be SCHWAB_401K_MANUAL
    v3 = next((s for s in strategies if s["strategy_id"] == "RAEC_401K_V3"), None)
    if v3:
        assert v3["book_id"] == "SCHWAB_401K_MANUAL"
    # S1 (decision) should be ALPACA_PAPER
    s1 = next((s for s in strategies if s["strategy_id"] == "S1_AVWAP_CORE"), None)
    if s1:
        assert s1["book_id"] == "ALPACA_PAPER"

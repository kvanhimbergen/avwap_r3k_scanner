from __future__ import annotations

import json
from pathlib import Path

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


def _write_strategy_states(repo_root: Path) -> None:
    """Write V3/V4/V5/COORD state files for the rebalance dashboard tests."""
    state_dir = repo_root / "state" / "strategies" / "SCHWAB_401K_MANUAL"
    state_dir.mkdir(parents=True, exist_ok=True)

    v3_state = {
        "last_confirmed_regime": "RISK_ON",
        "last_eval_date": "2026-02-10",
        "last_regime": "RISK_ON",
        "last_rebalance_date": "2026-02-10",
        "last_targets": {"TQQQ": 35.0, "SOXL": 25.0, "BIL": 40.0},
        "last_known_allocations": {"SPY": 50.0, "BIL": 50.0},
        "regime_smoother": {
            "confirmed_regime": "RISK_ON",
            "history": [{"date": "2026-02-10", "regime": "RISK_ON", "confidence": 1.0}],
            "smoothing_days": 3,
        },
    }
    (state_dir / "RAEC_401K_V3.json").write_text(json.dumps(v3_state), encoding="utf-8")

    v4_state = {
        "last_confirmed_regime": "TRANSITION",
        "last_eval_date": "2026-02-10",
        "last_regime": "TRANSITION",
        "last_rebalance_date": "2026-02-10",
        "last_targets": {"GLD": 30.0, "IEF": 40.0, "BIL": 30.0},
        "last_known_allocations": {"GLD": 30.0, "IEF": 40.0, "BIL": 30.0},
        "regime_smoother": {
            "confirmed_regime": "TRANSITION",
            "history": [{"date": "2026-02-10", "regime": "TRANSITION", "confidence": 1.0}],
            "smoothing_days": 3,
        },
    }
    (state_dir / "RAEC_401K_V4.json").write_text(json.dumps(v4_state), encoding="utf-8")

    v5_state = {
        "last_confirmed_regime": "RISK_ON",
        "last_eval_date": "2026-02-10",
        "last_regime": "RISK_ON",
        "last_rebalance_date": "2026-02-10",
        "last_targets": {"SMH": 50.0, "BIL": 30.0, "SOXL": 20.0},
        "last_known_allocations": {"SMH": 50.0, "BIL": 30.0, "SOXL": 20.0},
        "regime_smoother": {
            "confirmed_regime": "RISK_ON",
            "history": [{"date": "2026-02-10", "regime": "RISK_ON", "confidence": 1.0}],
            "smoothing_days": 3,
        },
    }
    (state_dir / "RAEC_401K_V5.json").write_text(json.dumps(v5_state), encoding="utf-8")

    coord_state = {
        "capital_split": {"v3": 0.4, "v4": 0.3, "v5": 0.3},
        "last_eval_date": "2026-02-10",
        "sub_rebalanced": ["v3", "v4", "v5"],
        "sub_regimes": {"v3": "RISK_ON", "v4": "TRANSITION", "v5": "RISK_ON"},
        "sub_smoothed_regimes": {"v3": "RISK_ON", "v4": "TRANSITION", "v5": "RISK_ON"},
    }
    (state_dir / "RAEC_401K_COORD.json").write_text(json.dumps(coord_state), encoding="utf-8")


def test_rebalance_dashboard_returns_200(analytics_settings) -> None:
    _write_strategy_states(analytics_settings.repo_root)
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/rebalance/dashboard")
    assert resp.status_code == 200


def test_rebalance_dashboard_has_required_fields(analytics_settings) -> None:
    _write_strategy_states(analytics_settings.repo_root)
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/rebalance/dashboard")
    data = resp.json()["data"]

    assert "strategies" in data
    assert "combined_target" in data
    assert "trades" in data
    assert "token_health" in data
    assert "portfolio_value" in data
    assert "current_positions" in data
    assert "last_sync_date" in data
    assert "positions_date" in data


def test_rebalance_dashboard_strategies(analytics_settings) -> None:
    _write_strategy_states(analytics_settings.repo_root)
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/rebalance/dashboard")
    data = resp.json()["data"]

    strategies = data["strategies"]
    assert len(strategies) == 3
    ids = {s["id"] for s in strategies}
    assert ids == {"RAEC_401K_V3", "RAEC_401K_V4", "RAEC_401K_V5"}

    v3 = next(s for s in strategies if s["id"] == "RAEC_401K_V3")
    assert v3["regime"] == "RISK_ON"
    assert v3["smoothed_regime"] == "RISK_ON"
    assert v3["weight"] == pytest.approx(0.4)
    assert "TQQQ" in v3["targets"]


def test_rebalance_dashboard_combined_target(analytics_settings) -> None:
    _write_strategy_states(analytics_settings.repo_root)
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/rebalance/dashboard")
    data = resp.json()["data"]

    ct = data["combined_target"]
    # V3: TQQQ 35*0.4=14, V4: none, V5: none → TQQQ=14
    assert ct["TQQQ"] == pytest.approx(14.0, abs=0.1)
    # BIL: V3 40*0.4=16, V4 30*0.3=9, V5 30*0.3=9 → 34
    assert ct["BIL"] == pytest.approx(34.0, abs=0.1)


def test_rebalance_dashboard_trades(analytics_settings) -> None:
    _write_strategy_states(analytics_settings.repo_root)
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/rebalance/dashboard")
    data = resp.json()["data"]

    trades = data["trades"]
    assert len(trades) > 0
    # All trades should have required fields
    for t in trades:
        assert "symbol" in t
        assert "side" in t
        assert t["side"] in ("BUY", "SELL")
        assert "current_pct" in t
        assert "target_pct" in t
        assert "delta_pct" in t
        assert "dollar_amount" in t
        assert "actionable" in t


def test_rebalance_dashboard_token_health(analytics_settings) -> None:
    _write_strategy_states(analytics_settings.repo_root)
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/rebalance/dashboard")
    data = resp.json()["data"]

    th = data["token_health"]
    assert "healthy" in th
    assert "days_until_expiry" in th
    assert "reason" in th

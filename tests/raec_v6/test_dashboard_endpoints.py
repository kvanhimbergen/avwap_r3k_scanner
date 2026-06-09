"""Tests for v6 dashboard query functions.

Construct a fixture repo with a state file + ledger, hit the query
functions, verify the response shape.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from analytics_platform.backend.api import queries
from strategies.raec_v6.shadow_book import ShadowBook


@pytest.fixture
def repo_with_v6_state(tmp_path: Path) -> Path:
    """Build a fake repo with v6 state + ledger + a V3/V4/V5 state file."""
    book = ShadowBook(starting_cash=230_000)
    asof = date(2026, 6, 1)
    for i in range(3):
        book.step(
            asof=asof + timedelta(days=i),
            target_weights={"SPY": 0.5, "BIL": 0.5},
            close_prices={"SPY": 600 + i, "BIL": 90},
        )

    state_dir = tmp_path / "state" / "strategies" / "RAEC_V6_DRY_RUN"
    state_dir.mkdir(parents=True)
    state_dir.joinpath("coordinator.json").write_text(json.dumps({
        "schema_version": 1,
        "started_at": asof.isoformat(),
        "last_eval_date": (asof + timedelta(days=2)).isoformat(),
        "prior_strategy_shares": {"V6_CROSS_ASSET_TREND": 0.4},
        "strategy_returns": {"V6_CROSS_ASSET_TREND": [0.001, 0.002, 0.003]},
        "dd_breaker_currently_active": False,
        "freeze_days_remaining": 0,
        "shadow_book": book.to_dict(),
    }))

    ledger_dir = tmp_path / "ledger" / "RAEC_V6"
    ledger_dir.mkdir(parents=True)
    last_asof = asof + timedelta(days=2)
    ledger_dir.joinpath(f"{last_asof.isoformat()}.jsonl").write_text(json.dumps({
        "record_type": "RAEC_V6_RUN",
        "ny_date": last_asof.isoformat(),
        "book_id": "RAEC_V6_DRY_RUN",
        "shadow_book": {"equity": book.equity, "cash": book.cash},
        "signal_state": {"regime_label": "RISK_ON", "regime_confidence": 0.8},
        "strategy_outputs": {
            "V6_CROSS_ASSET_TREND": {
                "weights": {"SPY": 0.3, "QQQ": 0.2},
                "conviction": 0.85,
                "regime_gate": 1.0,
                "realized_vol_60d": 0.14,
                "diagnostics": {},
            },
            "V6_BOND_CARRY": None,  # simulate a failed strategy
        },
        "allocator": {
            "strategy_shares": {"V6_CROSS_ASSET_TREND": 0.4, "V6_BOND_CARRY": 0.0},
            "failed_strategies": ["V6_BOND_CARRY"],
        },
        "overlay": {
            "exposure_scale": 1.2,
            "target_vol": 0.24,
            "forecast_vol": 0.13,
            "dd_breaker_active": False,
            "shock_day_detected": False,
            "freeze_rebalancing_until_idx": 0,
        },
        "book_targets_pre_overlay": {"SPY": 0.12, "QQQ": 0.08},
        "final_weights": {"SPY": 0.144, "QQQ": 0.096},
        "rebalance": True,
        "notice": None,
        "drift_l1_pct": 6.0,
        "intents": [],
    }) + "\n")

    # A V3 state file with last_targets so divergence has something to diff against.
    live_dir = tmp_path / "state" / "strategies" / "SCHWAB_401K_MANUAL"
    live_dir.mkdir(parents=True)
    live_dir.joinpath("RAEC_401K_V3.json").write_text(json.dumps({
        "last_targets": {"SPY": 60.0, "BIL": 40.0},
    }))
    live_dir.joinpath("RAEC_401K_V4.json").write_text(json.dumps({
        "last_targets": {"EEM": 50.0, "PDBC": 50.0},
    }))
    live_dir.joinpath("RAEC_401K_V5.json").write_text(json.dumps({
        "last_targets": {"AIQ": 100.0},
    }))

    return tmp_path


def test_shadow_book_empty_when_no_state(tmp_path: Path) -> None:
    """No state file → dry_run_active False, no rows."""
    result = queries.get_v6_shadow_book(None, tmp_path)
    assert result["dry_run_active"] is False
    assert result["rows"] == []


def test_shadow_book_returns_series_and_positions(repo_with_v6_state: Path) -> None:
    result = queries.get_v6_shadow_book(None, repo_with_v6_state)
    assert result["dry_run_active"] is True
    assert len(result["series"]) == 3  # 3 trading days
    assert all("asof" in p and "equity" in p for p in result["series"])
    assert result["positions"]
    assert all("symbol" in p and "weight_pct" in p for p in result["positions"])
    s = result["summary"]
    assert s["starting_cash"] == 230_000
    assert s["dd_breaker_active"] is False


def test_allocator_state_empty_when_no_ledger(tmp_path: Path) -> None:
    result = queries.get_v6_allocator_state(None, tmp_path)
    assert result["dry_run_active"] is False
    assert result["strategies"] == []


def test_allocator_state_returns_per_strategy_rows(repo_with_v6_state: Path) -> None:
    result = queries.get_v6_allocator_state(None, repo_with_v6_state)
    assert result["dry_run_active"] is True
    sids = {row["strategy_id"] for row in result["strategies"]}
    assert "V6_CROSS_ASSET_TREND" in sids
    assert "V6_BOND_CARRY" in sids
    # Failed strategy shows failed=True with None conviction
    failed_row = next(r for r in result["strategies"] if r["strategy_id"] == "V6_BOND_CARRY")
    assert failed_row["failed"] is True
    assert failed_row["conviction"] is None
    # Overlay exposure_scale surfaces
    assert result["overlay"]["exposure_scale"] == 1.2
    assert result["regime"] == "RISK_ON"


def test_divergence_empty_when_no_ledger(tmp_path: Path) -> None:
    result = queries.get_v6_divergence(None, tmp_path)
    assert result["dry_run_active"] is False
    assert result["l1_distance_pct"] is None


def test_divergence_computes_per_symbol_delta(repo_with_v6_state: Path) -> None:
    result = queries.get_v6_divergence(None, repo_with_v6_state)
    assert result["dry_run_active"] is True
    assert result["l1_distance_pct"] is not None
    assert result["l1_distance_pct"] > 0
    # Top-row by abs delta should be the biggest disagreement
    if result["rows"]:
        for r in result["rows"]:
            assert "symbol" in r
            assert "v6_pct" in r
            assert "live_pct" in r
            assert "delta_pct" in r

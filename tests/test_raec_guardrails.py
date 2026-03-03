"""Tests for regime smoothing + rebalance cooldown guardrails."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from analytics.regime_transition import RegimeTransitionDetector
from data.prices import FixturePriceProvider
from helpers import linear_series as _linear_series
from strategies import raec_401k_v3


def _risk_on_provider() -> FixturePriceProvider:
    start = date(2024, 1, 1)
    series = {
        "VTI": _linear_series(start=start, base=100, slope=0.34, wiggle=0.30),
        "TQQQ": _linear_series(start=start, base=50, slope=0.90, wiggle=1.20),
        "SOXL": _linear_series(start=start, base=30, slope=0.85, wiggle=1.50),
        "UPRO": _linear_series(start=start, base=60, slope=0.70, wiggle=0.90),
        "TECL": _linear_series(start=start, base=40, slope=0.80, wiggle=1.10),
        "FNGU": _linear_series(start=start, base=25, slope=0.95, wiggle=1.80),
        "XLK": _linear_series(start=start, base=100, slope=0.45, wiggle=0.35),
        "SMH": _linear_series(start=start, base=100, slope=0.50, wiggle=0.50),
        "XLY": _linear_series(start=start, base=100, slope=0.30, wiggle=0.25),
        "XLC": _linear_series(start=start, base=100, slope=0.28, wiggle=0.20),
        "XLI": _linear_series(start=start, base=100, slope=0.22, wiggle=0.18),
        "QQQ": _linear_series(start=start, base=100, slope=0.48, wiggle=0.45),
        "SPY": _linear_series(start=start, base=100, slope=0.30, wiggle=0.25),
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20),
        "USMV": _linear_series(start=start, base=100, slope=0.18, wiggle=0.10),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _seed_state(repo_root: Path, state: dict) -> None:
    state_path = (
        repo_root / "state" / "strategies" / raec_401k_v3.BOOK_ID / f"{raec_401k_v3.STRATEGY_ID}.json"
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state))


def _compute_targets(provider: FixturePriceProvider, asof_date: str = "2026-02-06") -> dict[str, float]:
    """Pre-compute V3 targets for a given provider and date."""
    asof = raec_401k_v3._parse_date(asof_date)
    cash_symbol = raec_401k_v3._get_cash_symbol(provider)
    vti_series = raec_401k_v3._sorted_series(provider.get_daily_close_series("VTI"), asof=asof)
    signal = raec_401k_v3._compute_anchor_signal(vti_series)
    feature_map = raec_401k_v3._load_symbol_features(provider=provider, asof=asof, cash_symbol=cash_symbol)
    return raec_401k_v3._targets_for_regime(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)


# ---------------------------------------------------------------------------
# First-ever run always rebalances
# ---------------------------------------------------------------------------

def test_first_run_always_rebalances(tmp_path: Path) -> None:
    """No prior state → should rebalance regardless."""
    provider = _risk_on_provider()
    # No state seeded at all
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=True,
    )
    assert result.should_rebalance is True


# ---------------------------------------------------------------------------
# Regime smoothing prevents single-day flip
# ---------------------------------------------------------------------------

def test_regime_smoothing_prevents_single_day_flip(tmp_path: Path) -> None:
    """A single day of different regime should NOT change smoothed_regime."""
    provider = _risk_on_provider()
    targets = _compute_targets(provider)

    # Seed state with confirmed RISK_OFF regime (smoother persisted)
    smoother = RegimeTransitionDetector(smoothing_days=3)
    smoother.update("RISK_OFF", 1.0, "2026-02-04")

    _seed_state(tmp_path, {
        "last_eval_date": "2026-02-05",
        "last_regime": "RISK_OFF",
        "last_confirmed_regime": "RISK_OFF",
        "last_rebalance_date": "2026-02-04",
        "last_known_allocations": {"TLT": 40.0, "GLD": 40.0, "BIL": 20.0},
        "regime_smoother": smoother.to_dict(),
    })

    # Provider signals RISK_ON (single day)
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=True,
    )
    # Raw regime is RISK_ON, but smoothed should stay RISK_OFF (only 1 day)
    assert result.regime == "RISK_ON"
    assert result.smoothed_regime == "RISK_OFF"


# ---------------------------------------------------------------------------
# Confirmed regime change after 3 consecutive days triggers rebalance
# ---------------------------------------------------------------------------

def test_confirmed_regime_change_triggers_rebalance(tmp_path: Path) -> None:
    """3 consecutive days of new regime confirms transition and triggers rebalance."""
    provider = _risk_on_provider()

    # Build a smoother that already has 2 days of RISK_ON after being RISK_OFF
    smoother = RegimeTransitionDetector(smoothing_days=3)
    smoother.update("RISK_OFF", 1.0, "2026-02-01")
    smoother.update("RISK_ON", 1.0, "2026-02-04")
    smoother.update("RISK_ON", 1.0, "2026-02-05")
    assert smoother._confirmed_regime == "RISK_OFF"  # not yet confirmed

    _seed_state(tmp_path, {
        "last_eval_date": "2026-02-05",
        "last_regime": "RISK_ON",
        "last_confirmed_regime": "RISK_OFF",
        "last_rebalance_date": "2026-02-05",  # just rebalanced (cooldown active)
        "last_known_allocations": {"TLT": 40.0, "GLD": 40.0, "BIL": 20.0},
        "regime_smoother": smoother.to_dict(),
    })

    # Day 3 of RISK_ON → confirms the transition
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=True,
    )
    assert result.smoothed_regime == "RISK_ON"
    # Regime change overrides cooldown
    assert result.should_rebalance is True


# ---------------------------------------------------------------------------
# Cooldown blocks rebalance
# ---------------------------------------------------------------------------

def test_cooldown_blocks_normal_drift(tmp_path: Path) -> None:
    """Within cooldown period, normal drift (< 2x threshold) does NOT trigger rebalance."""
    provider = _risk_on_provider()
    targets = _compute_targets(provider)

    # Build smoother with confirmed RISK_ON
    smoother = RegimeTransitionDetector(smoothing_days=3)
    smoother.update("RISK_ON", 1.0, "2026-02-06")

    # Seed allocs with 1.6% drift (above 1.5% threshold, below 3.0% extreme)
    drifted_allocs = {sym: pct for sym, pct in targets.items()}
    first_sym = next(iter(drifted_allocs))
    other_syms = [s for s in drifted_allocs if s != first_sym]
    drifted_allocs[first_sym] += 1.6
    if other_syms:
        drifted_allocs[other_syms[0]] -= 1.6

    _seed_state(tmp_path, {
        "last_eval_date": "2026-02-05",
        "last_regime": "RISK_ON",
        "last_confirmed_regime": "RISK_ON",
        "last_rebalance_date": "2026-02-05",  # 1 day ago (within 5-day cooldown)
        "last_known_allocations": drifted_allocs,
        "regime_smoother": smoother.to_dict(),
    })

    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    # Normal drift during cooldown → no rebalance
    assert result.should_rebalance is False


# ---------------------------------------------------------------------------
# Extreme drift overrides cooldown
# ---------------------------------------------------------------------------

def test_extreme_drift_overrides_cooldown(tmp_path: Path) -> None:
    """Extreme drift (>2x threshold) overrides cooldown and triggers rebalance."""
    provider = _risk_on_provider()
    targets = _compute_targets(provider)

    smoother = RegimeTransitionDetector(smoothing_days=3)
    smoother.update("RISK_ON", 1.0, "2026-02-06")

    # V3 drift threshold is 1.5%, so 2x = 3.0%. Create drift > 3.0%
    extreme_allocs = {sym: pct for sym, pct in targets.items()}
    first_sym = next(iter(extreme_allocs))
    other_syms = [s for s in extreme_allocs if s != first_sym]
    extreme_allocs[first_sym] += 3.5
    if other_syms:
        extreme_allocs[other_syms[0]] -= 3.5

    _seed_state(tmp_path, {
        "last_eval_date": "2026-02-05",
        "last_regime": "RISK_ON",
        "last_confirmed_regime": "RISK_ON",
        "last_rebalance_date": "2026-02-05",  # 1 day ago (within cooldown)
        "last_known_allocations": extreme_allocs,
        "regime_smoother": smoother.to_dict(),
    })

    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    # Extreme drift overrides cooldown
    assert result.should_rebalance is True


# ---------------------------------------------------------------------------
# Cooldown expires → normal drift triggers rebalance
# ---------------------------------------------------------------------------

def test_cooldown_expired_normal_drift_triggers(tmp_path: Path) -> None:
    """After cooldown expires, normal drift triggers rebalance again."""
    provider = _risk_on_provider()
    targets = _compute_targets(provider)

    smoother = RegimeTransitionDetector(smoothing_days=3)
    smoother.update("RISK_ON", 1.0, "2026-02-06")

    # 1.6% drift (above 1.5% threshold)
    drifted_allocs = {sym: pct for sym, pct in targets.items()}
    first_sym = next(iter(drifted_allocs))
    other_syms = [s for s in drifted_allocs if s != first_sym]
    drifted_allocs[first_sym] += 1.6
    if other_syms:
        drifted_allocs[other_syms[0]] -= 1.6

    _seed_state(tmp_path, {
        "last_eval_date": "2026-02-05",
        "last_regime": "RISK_ON",
        "last_confirmed_regime": "RISK_ON",
        "last_rebalance_date": "2026-01-30",  # 7 days ago (cooldown expired)
        "last_known_allocations": drifted_allocs,
        "regime_smoother": smoother.to_dict(),
    })

    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    assert result.should_rebalance is True


# ---------------------------------------------------------------------------
# State persistence: smoother + last_rebalance_date written
# ---------------------------------------------------------------------------

def test_state_persists_smoother_and_rebalance_date(tmp_path: Path) -> None:
    """After a run, state should contain regime_smoother and last_rebalance_date."""
    provider = _risk_on_provider()

    # First run (no prior state)
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=True,
    )
    assert result.should_rebalance is True

    state_path = (
        tmp_path / "state" / "strategies" / raec_401k_v3.BOOK_ID / f"{raec_401k_v3.STRATEGY_ID}.json"
    )
    state = json.loads(state_path.read_text())

    assert "regime_smoother" in state
    assert state["regime_smoother"]["confirmed_regime"] is not None
    assert "last_confirmed_regime" in state
    assert state["last_rebalance_date"] == "2026-02-06"


# ---------------------------------------------------------------------------
# RunResult exposes both raw and smoothed regime
# ---------------------------------------------------------------------------

def test_run_result_has_both_regimes(tmp_path: Path) -> None:
    """RunResult.regime is raw, RunResult.smoothed_regime is smoothed."""
    provider = _risk_on_provider()
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=True,
    )
    # On first run, both should match (first observation accepted immediately)
    assert result.regime == result.smoothed_regime
    assert result.regime in ("RISK_ON", "RISK_OFF", "TRANSITION")

"""Tests for the allocator: caps, net-out, failed-strategy routing, turnover damper."""

from __future__ import annotations

from strategies.raec_v6.allocator import allocate
from strategies.raec_v6.manifest import StrategyManifest
from strategies.raec_v6.strategy_output import StrategyOutput


def _out(
    *,
    sid: str,
    weights: dict[str, float],
    conviction: float = 1.0,
    regime_gate: float = 1.0,
    vol: float = 0.20,
    max_share_cap: float = 1.0,
    backtest_prior: float = 1.0,
) -> StrategyOutput:
    m = StrategyManifest(
        strategy_id=sid,
        asset_classes=("equity_us_broad",),
        max_share_cap=max_share_cap,
        backtest_oos_sharpe=backtest_prior,
    )
    return StrategyOutput(
        weights=weights,
        conviction=conviction,
        regime_gate=regime_gate,
        realized_vol_60d=vol,
        manifest=m,
    )


def test_single_strategy_share_at_max_cap() -> None:
    """One strategy with max_share_cap=0.4 should end at 0.4 share; rest is cash.
    Pass per_symbol_cap=1.0 to isolate the strategy-share cap from the per-symbol one."""
    out = _out(sid="S1", weights={"SPY": 1.0}, max_share_cap=0.4)
    res = allocate(outputs={"S1": out}, per_symbol_cap=1.0)
    assert abs(res.strategy_shares["S1"] - 0.4) < 1e-9
    assert abs(res.book_targets["SPY"] - 0.4) < 1e-9


def test_two_strategies_risk_parity_when_uncapped() -> None:
    """Same vol, no caps → both get ~0.5 share."""
    a = _out(sid="A", weights={"SPY": 1.0}, vol=0.20)
    b = _out(sid="B", weights={"QQQ": 1.0}, vol=0.20)
    res = allocate(outputs={"A": a, "B": b})
    assert abs(res.strategy_shares["A"] - 0.5) < 0.01
    assert abs(res.strategy_shares["B"] - 0.5) < 0.01


def test_lower_vol_gets_more_share() -> None:
    """Risk parity: lower vol gets more share."""
    low = _out(sid="LO", weights={"BIL": 1.0}, vol=0.05)
    high = _out(sid="HI", weights={"SOXL": 1.0}, vol=0.50)
    res = allocate(outputs={"LO": low, "HI": high})
    assert res.strategy_shares["LO"] > res.strategy_shares["HI"]


def test_failed_strategy_share_routed_to_cash() -> None:
    """A None output is treated as failed and tracked separately."""
    a = _out(sid="A", weights={"SPY": 1.0})
    res = allocate(outputs={"A": a, "BROKEN": None})
    assert res.failed_strategies == ("BROKEN",)
    assert "BROKEN" not in res.strategy_shares


def test_zero_gate_zeros_share() -> None:
    """A strategy declaring regime_gate=0 gets 0 share."""
    on = _out(sid="ON", weights={"SPY": 1.0})
    off = _out(sid="OFF", weights={"PSQ": 1.0}, regime_gate=0.0)
    res = allocate(outputs={"ON": on, "OFF": off})
    assert res.strategy_shares["OFF"] == 0.0
    assert res.strategy_shares["ON"] > 0.0


def test_per_symbol_cap_applied_to_book() -> None:
    """Two strategies both picking SPY heavily → SPY capped at 25%."""
    a = _out(sid="A", weights={"SPY": 1.0}, max_share_cap=1.0)
    b = _out(sid="B", weights={"SPY": 1.0}, max_share_cap=1.0)
    res = allocate(outputs={"A": a, "B": b}, per_symbol_cap=0.25)
    assert res.book_targets["SPY"] <= 0.25 + 1e-9


def test_lower_conviction_lower_share() -> None:
    """Risk parity equal but lower conviction → less share."""
    hi = _out(sid="HI", weights={"SPY": 1.0}, conviction=1.0)
    lo = _out(sid="LO", weights={"QQQ": 1.0}, conviction=0.1)
    res = allocate(outputs={"HI": hi, "LO": lo})
    assert res.strategy_shares["HI"] > res.strategy_shares["LO"]


def test_turnover_damper_limits_share_jump() -> None:
    """If yesterday's share was 0 and today wants 0.5, damped at 0.05."""
    out = _out(sid="A", weights={"SPY": 1.0}, max_share_cap=1.0)
    res = allocate(
        outputs={"A": out},
        prior_shares={"A": 0.0},
        turnover_damper_per_day=0.05,
    )
    assert res.strategy_shares["A"] <= 0.05 + 1e-9


def test_all_failed_returns_empty_book() -> None:
    res = allocate(outputs={"A": None, "B": None})
    assert res.book_targets == {}
    assert set(res.failed_strategies) == {"A", "B"}


def test_zero_vol_strategy_does_not_dominate() -> None:
    """A strategy with realized_vol=0 should NOT get infinite share."""
    zero = _out(sid="Z", weights={"SPY": 1.0}, vol=0.0)
    norm = _out(sid="N", weights={"QQQ": 1.0}, vol=0.20)
    res = allocate(outputs={"Z": zero, "N": norm})
    # Z should have 0 share (no info → defer); N should get the share.
    assert res.strategy_shares["Z"] == 0.0
    assert res.strategy_shares["N"] > 0.0

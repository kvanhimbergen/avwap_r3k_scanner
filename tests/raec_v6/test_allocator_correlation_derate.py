"""Tests for the allocator's correlation derate."""

from __future__ import annotations

import random

from strategies.raec_v6.allocator import (
    _correlation_derate,
    _pairwise_correlation,
    allocate,
)
from strategies.raec_v6.manifest import StrategyManifest
from strategies.raec_v6.strategy_output import StrategyOutput


def _out(sid: str, weights: dict[str, float], *, vol: float = 0.2,
         max_share_cap: float = 1.0) -> StrategyOutput:
    m = StrategyManifest(
        strategy_id=sid,
        asset_classes=("equity_us_broad",),
        max_share_cap=max_share_cap,
        backtest_oos_sharpe=1.0,
    )
    return StrategyOutput(
        weights=weights, conviction=1.0, regime_gate=1.0,
        realized_vol_60d=vol, manifest=m,
    )


def test_pairwise_correlation_basic() -> None:
    random.seed(0)
    a = [random.gauss(0, 0.01) for _ in range(100)]
    b = [x + 0.001 for x in a]  # near-perfect
    c = [random.gauss(0, 0.01) for _ in range(100)]
    assert _pairwise_correlation(a, b) > 0.99
    assert abs(_pairwise_correlation(a, c)) < 0.5


def test_pairwise_correlation_too_short_returns_none() -> None:
    assert _pairwise_correlation([0.1], [0.2]) is None


def test_pairwise_correlation_zero_variance_returns_none() -> None:
    """Zero variance series → undefined correlation → None."""
    flat = [0.01] * 50
    other = [0.01 * i for i in range(50)]
    assert _pairwise_correlation(flat, other) is None


def test_derate_no_history_returns_input() -> None:
    """No strategy_returns → no change."""
    raw = {"A": 1.0, "B": 1.0}
    out = _correlation_derate(raw, None)
    assert out == raw


def test_derate_uncorrelated_no_change() -> None:
    """Strategies with low correlation should not be derated."""
    random.seed(42)
    a = [random.gauss(0, 0.01) for _ in range(80)]
    b = [random.gauss(0, 0.01) for _ in range(80)]  # independent
    raw = {"A": 1.0, "B": 1.0}
    out = _correlation_derate(raw, {"A": a, "B": b}, threshold=0.7)
    # Both should be approximately unchanged.
    assert abs(out["A"] - 1.0) < 0.05
    assert abs(out["B"] - 1.0) < 0.05


def test_derate_highly_correlated_pair_does_NOT_derate() -> None:
    """Two strategies with avg corr 1.0 each (vs each other only) → avg = 1.0
    > 0.7 → both should derate. Threshold check for the single-pair case."""
    random.seed(42)
    a = [random.gauss(0, 0.01) for _ in range(80)]
    b = [x + 0.0001 for x in a]
    raw = {"A": 1.0, "B": 1.0}
    out = _correlation_derate(raw, {"A": a, "B": b}, threshold=0.7)
    # With only one pair, A's avg corr == corr(A,B) == ~1.0; should derate.
    assert out["A"] < 1.0
    assert out["B"] < 1.0


def test_derate_diversifier_unaffected_in_3_strategy_mix() -> None:
    """A correlates with B (not C). Both A and B are correlated; C is not."""
    random.seed(42)
    a = [random.gauss(0, 0.01) for _ in range(80)]
    b = [x + 0.0001 for x in a]
    c = [random.gauss(0, 0.01) for _ in range(80)]
    raw = {"A": 1.0, "B": 1.0, "C": 1.0}
    out = _correlation_derate(raw, {"A": a, "B": b, "C": c}, threshold=0.7)
    # A's avg corr = mean(corr(A,B)=~1.0, corr(A,C)~0) = ~0.5 < 0.7 → no derate
    # Same for B and C.
    for sid in ("A", "B", "C"):
        assert abs(out[sid] - 1.0) < 0.05


def test_derate_floor_at_50_percent() -> None:
    """Even perfectly-correlated strategies don't get derated below the floor."""
    random.seed(42)
    a = [random.gauss(0, 0.01) for _ in range(80)]
    # 5 strategies all near-perfectly correlated with each other.
    rets = {f"S{i}": [x + (i * 0.0001) for x in a] for i in range(5)}
    raw = {sid: 1.0 for sid in rets}
    out = _correlation_derate(raw, rets, threshold=0.7, floor=0.5)
    for v in out.values():
        assert v >= 0.5 - 1e-9


def test_strategies_with_thin_history_skip_derate() -> None:
    """A strategy with <30d of returns participates neither in derating
    others nor in being derated."""
    random.seed(42)
    long_ret = [random.gauss(0, 0.01) for _ in range(80)]
    short_ret = [random.gauss(0, 0.01) for _ in range(10)]
    raw = {"LONG": 1.0, "SHORT": 1.0}
    out = _correlation_derate(raw, {"LONG": long_ret, "SHORT": short_ret})
    # LONG alone has no peer → no derate.
    assert out["LONG"] == 1.0
    assert out["SHORT"] == 1.0


def test_allocate_with_correlated_strategies_routes_less_share_to_them() -> None:
    """End-to-end: correlated strategies should get less combined share than
    uncorrelated ones with the same individual vol."""
    random.seed(42)
    a = [random.gauss(0, 0.01) for _ in range(80)]
    b = [x + 0.0001 for x in a]
    c = [random.gauss(0, 0.01) for _ in range(80)]
    d = [random.gauss(0, 0.01) for _ in range(80)]

    correlated_pair = allocate(
        outputs={
            "A": _out("A", {"SPY": 1.0}),
            "B": _out("B", {"QQQ": 1.0}),  # different symbols but correlated returns
        },
        strategy_returns={"A": a, "B": b},
        per_symbol_cap=1.0,
    )
    uncorrelated_pair = allocate(
        outputs={
            "C": _out("C", {"SPY": 1.0}),
            "D": _out("D", {"QQQ": 1.0}),
        },
        strategy_returns={"C": c, "D": d},
        per_symbol_cap=1.0,
    )
    correlated_total = sum(correlated_pair.strategy_shares.values())
    uncorrelated_total = sum(uncorrelated_pair.strategy_shares.values())
    # The correlated pair should end up with less aggregate share (more cash residual).
    assert correlated_total < uncorrelated_total

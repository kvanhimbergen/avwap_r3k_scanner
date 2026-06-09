"""Test the per-symbol cap policy splits ETFs vs single names."""

from __future__ import annotations

from strategies.raec_v6.allocator import allocate
from strategies.raec_v6.manifest import StrategyManifest
from strategies.raec_v6.strategy_output import StrategyOutput


def _out(*, sid: str, weights: dict[str, float], max_share: float = 1.0) -> StrategyOutput:
    m = StrategyManifest(
        strategy_id=sid,
        asset_classes=("equity_us_broad",),
        max_share_cap=max_share,
        backtest_oos_sharpe=1.0,
    )
    return StrategyOutput(
        weights=weights, conviction=1.0, regime_gate=1.0,
        realized_vol_60d=0.20, manifest=m,
    )


def test_etf_uses_etf_cap() -> None:
    """SPY is in asset_classes.yaml → ETF cap (0.25) applies."""
    out = _out(sid="A", weights={"SPY": 1.0})
    res = allocate(
        outputs={"A": out},
        per_symbol_cap=0.25,
        single_name_per_symbol_cap=0.10,
    )
    assert res.book_targets["SPY"] <= 0.25 + 1e-9
    assert res.book_targets["SPY"] > 0.10  # not the tighter single-name cap


def test_single_name_uses_tighter_cap() -> None:
    """NVDA is NOT in asset_classes.yaml → single-name cap (0.10) applies."""
    out = _out(sid="A", weights={"NVDA": 1.0})
    res = allocate(
        outputs={"A": out},
        per_symbol_cap=0.25,
        single_name_per_symbol_cap=0.10,
    )
    assert res.book_targets["NVDA"] <= 0.10 + 1e-9


def test_mixed_book_applies_correct_cap_per_symbol() -> None:
    """A strategy holding both ETF and single names → each gets the right cap."""
    out = _out(sid="A", weights={"SPY": 0.4, "NVDA": 0.4, "MSFT": 0.2})
    res = allocate(
        outputs={"A": out},
        per_symbol_cap=0.25,
        single_name_per_symbol_cap=0.10,
    )
    # SPY: ETF → 25% cap (gets full 0.4 → capped at 0.25)
    assert res.book_targets["SPY"] <= 0.25 + 1e-9
    # NVDA & MSFT: single names → 10% cap
    assert res.book_targets["NVDA"] <= 0.10 + 1e-9
    assert res.book_targets["MSFT"] <= 0.10 + 1e-9

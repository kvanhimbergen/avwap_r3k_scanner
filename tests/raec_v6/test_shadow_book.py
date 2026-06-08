"""Tests for ShadowBook."""

from __future__ import annotations

from datetime import date, timedelta

from strategies.raec_v6.shadow_book import ShadowBook


def test_initial_state() -> None:
    b = ShadowBook(starting_cash=100_000)
    assert b.equity == 100_000
    assert b.cash == 100_000
    assert b.positions == {}


def test_first_step_opens_positions() -> None:
    b = ShadowBook(starting_cash=100_000, slippage_bps=0)
    asof = date(2026, 1, 5)
    r = b.step(
        asof=asof,
        target_weights={"SPY": 0.6, "BIL": 0.4},
        close_prices={"SPY": 600, "BIL": 90},
    )
    assert r.equity == 100_000  # no MTM change on day 1, no slippage
    assert abs(r.positions["SPY"] - 60_000) < 1
    assert abs(r.positions["BIL"] - 40_000) < 1


def test_slippage_reduces_equity_on_trade() -> None:
    b = ShadowBook(starting_cash=100_000, slippage_bps=10)  # 10bps
    asof = date(2026, 1, 5)
    r = b.step(
        asof=asof,
        target_weights={"SPY": 1.0},
        close_prices={"SPY": 600},
    )
    # Slippage of 10bps × 100k traded = $100; equity should be $99,900
    assert r.equity < 100_000
    assert r.equity > 99_800  # close to expected


def test_mtm_advances_equity() -> None:
    b = ShadowBook(starting_cash=100_000, slippage_bps=0)
    asof = date(2026, 1, 5)
    b.step(asof=asof, target_weights={"SPY": 1.0}, close_prices={"SPY": 600})
    # Day 2: SPY +10%; equity should be ~+10%
    r2 = b.step(asof=asof + timedelta(days=1), target_weights={"SPY": 1.0},
                close_prices={"SPY": 660})
    assert 109_500 < r2.equity < 110_500  # rebalance may trade small amounts


def test_rotation_sells_and_buys() -> None:
    b = ShadowBook(starting_cash=100_000, slippage_bps=0)
    asof = date(2026, 1, 5)
    b.step(asof=asof, target_weights={"SPY": 1.0}, close_prices={"SPY": 600})
    # Day 2: rotate to BIL
    r2 = b.step(asof=asof + timedelta(days=1), target_weights={"BIL": 1.0},
                close_prices={"SPY": 600, "BIL": 90})
    symbols = {t.symbol for t in r2.trades}
    sides = {(t.symbol, t.side) for t in r2.trades}
    assert "SPY" in symbols
    assert "BIL" in symbols
    assert ("SPY", "SELL") in sides
    assert ("BIL", "BUY") in sides


def test_min_trade_pct_filters_tiny_orders() -> None:
    b = ShadowBook(starting_cash=100_000, slippage_bps=0)
    asof = date(2026, 1, 5)
    b.step(asof=asof, target_weights={"SPY": 0.50}, close_prices={"SPY": 600, "BIL": 90})
    # Day 2: 0.501 vs 0.50 = 0.1pp delta — below default 0.5% min trade. No trade.
    r2 = b.step(asof=asof + timedelta(days=1), target_weights={"SPY": 0.501},
                close_prices={"SPY": 600, "BIL": 90}, min_trade_pct=0.5)
    # We did add cash position implicit, so no trade for SPY. May trade BIL though.
    spy_trades = [t for t in r2.trades if t.symbol == "SPY"]
    assert spy_trades == []


def test_summary_contains_expected_metrics() -> None:
    b = ShadowBook(starting_cash=100_000, slippage_bps=0)
    asof = date(2026, 1, 5)
    for i in range(20):
        px = 600 * (1.005 ** i)
        b.step(asof=asof + timedelta(days=i), target_weights={"SPY": 1.0},
               close_prices={"SPY": px})
    s = b.summary()
    for k in ("total_return", "cagr", "max_drawdown", "sharpe", "realized_vol_annualized",
              "n_trading_days", "n_trades"):
        assert k in s
    assert s["n_trading_days"] == 20
    assert s["total_return"] > 0  # SPY trending up

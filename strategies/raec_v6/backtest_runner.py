"""RAEC v6 portfolio backtest.

Runs the v6 ensemble end-to-end over a historical date range:
- builds a per-day SignalState (only the signals each phase's strategies need)
- calls each strategy.compute()
- runs the allocator
- runs the overlay (vol scale + DD breaker)
- applies the resulting target weights to a ShadowBook
- records equity curve + summary + SPY benchmark comparison

Phase A scope: 1 strategy (CrossAssetTrend). Future phases add more
strategies; this file adapts by importing them at the top.

Usage:
    venv/bin/python -m strategies.raec_v6.backtest_runner \\
        --start 2022-01-01 --end 2026-06-01 --out backtests/raec_v6_phase_a/

Output is written under backtests/ (which is .gitignored — outputs only).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from analytics.deflated_sharpe import deflated_sharpe_ratio
from data.prices import FixturePriceProvider, get_default_price_provider
from strategies.raec_v6 import asset_classes as ac
from strategies.raec_v6.allocator import allocate
from strategies.raec_v6.overlay import apply_overlay
from strategies.raec_v6.shadow_book import ShadowBook
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.signals.cross_asset_trend import (
    REPRESENTATIVES,
    compute_cross_asset_trend,
)
from strategies.raec_v6.signals.vol_percentile import compute_vol_percentile
from strategies.raec_v6.strategies.cross_asset_trend import CrossAssetTrend
from strategies.raec_v6.strategies.equity_leveraged_momentum import (
    EquityLeveragedMomentum,
    _RISK_UNIVERSE as EQUITY_LEV_UNIVERSE,
)
from strategies.raec_v6.strategies.sector_relative_strength import (
    SectorRelativeStrength,
)
from strategies.raec_v6.strategies.thematic_conviction import ThematicConviction


# Symbols the backtest needs prices for:
# - representative ETFs of each tracked asset class (cross-asset trend)
# - equity-leveraged universe (broad + leveraged + sector + leveraged sector)
# - all sectors (for SectorRelativeStrength)
# - all themes (for ThematicConviction)
# - SPY benchmark + cash equivalent BIL
_BT_SYMBOLS: tuple[str, ...] = tuple(
    sorted(
        set(REPRESENTATIVES.values())
        | set(EQUITY_LEV_UNIVERSE)
        | set(ac.get_symbols_in_class("sector"))
        | set(ac.get_symbols_in_class("theme"))
        | {"SPY", "BIL"}
    )
)


def _prefetch_prices(
    symbols: Iterable[str], period: str = "10y"
) -> FixturePriceProvider:
    """Fetch each symbol via yfinance once and serve from memory.

    yfinance is slow for repeated single-symbol calls; this caches the
    full history of every symbol upfront so the backtest loop is O(1)
    per get_daily_close_series.
    """
    src = get_default_price_provider(".", period=period)
    cache: dict[str, list[tuple[date, float]]] = {}
    for sym in sorted(set(s.upper() for s in symbols)):
        series = src.get_daily_close_series(sym)
        if series:
            cache[sym] = series
        else:
            print(f"[bt] WARN: no data for {sym}; skipping.")
    return FixturePriceProvider(cache)


def _close_at(
    provider: FixturePriceProvider, symbol: str, asof: date
) -> float | None:
    """Last close ≤ asof for symbol, or None if no data."""
    series = provider.get_daily_close_series(symbol)
    if not series:
        return None
    # series is ordered; walk from end
    for d, c in reversed(series):
        if d <= asof:
            return c
    return None


def _daily_returns_window(
    provider: FixturePriceProvider, symbol: str, asof: date, n: int
) -> list[float]:
    series = provider.get_daily_close_series(symbol)
    closes = [c for d, c in series if d <= asof]
    if len(closes) < 2:
        return []
    closes = closes[-(n + 1) :]
    rs: list[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            rs.append(closes[i] / closes[i - 1] - 1.0)
    return rs


def _spy_realized_vol_60d(provider: FixturePriceProvider, asof: date) -> float:
    rs = _daily_returns_window(provider, "SPY", asof, 60)
    if len(rs) < 20:
        return 0.0
    mean = sum(rs) / len(rs)
    var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
    if var <= 0:
        return 0.0
    return math.sqrt(var) * math.sqrt(252)


def _is_trading_day(provider: FixturePriceProvider, asof: date) -> bool:
    """SPY traded on this date in the cache."""
    series = provider.get_daily_close_series("SPY")
    return any(d == asof for d, _ in series)


def run_backtest(
    *,
    start: date,
    end: date,
    starting_cash: float = 230_000.0,
    rebalance_threshold_pct: float = 5.0,  # L1 drift threshold for trade
    out_dir: Path | None = None,
) -> dict:
    """Run the v6 backtest. Returns a summary dict; writes CSV/JSON if out_dir given."""
    provider = _prefetch_prices(_BT_SYMBOLS)
    book = ShadowBook(starting_cash=starting_cash, slippage_bps=5.0)
    spy_curve: list[float] = []  # SPY equity curve for benchmark
    spy_shares: float | None = None

    strategies = [
        CrossAssetTrend(top_k=4),
        EquityLeveragedMomentum(top_k=5),
        SectorRelativeStrength(top_k=4),
        ThematicConviction(top_k=3),
    ]
    strategy_ids = [s.manifest.strategy_id for s in strategies]

    prior_strategy_shares: dict[str, float] = {sid: 0.0 for sid in strategy_ids}
    # Per-strategy daily returns (for correlation derate). Updated each step
    # from the prior day's strategy_shares × per-symbol returns.
    strategy_returns: dict[str, list[float]] = {sid: [] for sid in strategy_ids}
    # Per-strategy yesterday's contribution (symbol -> notional weight). Used
    # to compute today's strategy return as Σ_sym weight × symbol_daily_return.
    prior_contributions: dict[str, dict[str, float]] = {sid: {} for sid in strategy_ids}
    dd_breaker_active = False
    freeze_days_remaining = 0

    # Walk trading days. We rebalance daily but the shadow book's
    # min_trade_pct filter will skip noise; we ADDITIONALLY skip trade
    # passes when L1 drift between current and target is < threshold.
    asof = start
    record: list[dict] = []
    while asof <= end:
        if not _is_trading_day(provider, asof):
            asof += timedelta(days=1)
            continue

        # SPY benchmark: full equity to SPY on day 1, then MTM only.
        spy_px = _close_at(provider, "SPY", asof)
        if spy_px is None or spy_px <= 0:
            asof += timedelta(days=1)
            continue
        if spy_shares is None:
            spy_shares = starting_cash / spy_px
        spy_curve.append(spy_shares * spy_px)

        # Per-symbol daily return: today vs prior trading day.
        # Used both to update strategy_returns (from prior_contributions) and
        # by the overlay's per-symbol vol estimate.
        # We compute a single daily return for each symbol the strategies
        # might care about, then use it.
        symbol_daily_returns: dict[str, float] = {}
        for sym in set().union(*(prior_contributions[sid].keys() for sid in strategy_ids)):
            ret_window = _daily_returns_window(provider, sym, asof, 2)
            if ret_window:
                symbol_daily_returns[sym] = ret_window[-1]

        # Update per-strategy daily return: Σ_sym weight × symbol_return.
        for sid in strategy_ids:
            r = 0.0
            for sym, w in prior_contributions[sid].items():
                r += w * symbol_daily_returns.get(sym, 0.0)
            strategy_returns[sid].append(r)

        # Build signals.
        trend = compute_cross_asset_trend(provider, asof)
        spy_vol = _spy_realized_vol_60d(provider, asof)
        # Vol percentile for SPY (used by EquityLeveragedMomentum's leverage gate).
        vol_pct = compute_vol_percentile(provider, ["SPY"], asof)
        state = SignalState(
            asof_date=asof,
            regime_label="UNKNOWN",  # E1 not wired into backtest yet
            regime_confidence=0.0,
            cross_asset_trend=trend,
            vol_percentile_252d=vol_pct,
            spy_realized_vol_60d=spy_vol,
            vix_implied=0.0,  # backtest skips VIX
        )

        # Call strategies.
        outputs: dict[str, object] = {}
        for strat in strategies:
            try:
                outputs[strat.manifest.strategy_id] = strat.compute(
                    signal_state=state, price_provider=provider, asof_date=asof
                )
            except Exception:
                outputs[strat.manifest.strategy_id] = None

        # Allocate (correlation derate only kicks in once strategies have ≥30d).
        has_history = {
            sid: len(strategy_returns[sid]) >= 20 for sid in strategy_ids
        }
        # Build recent Sharpe per strategy (60d rolling).
        recent_sharpes = {}
        for sid in strategy_ids:
            rets = strategy_returns[sid][-60:]
            if len(rets) >= 20:
                m = sum(rets) / len(rets)
                v = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
                import math as _m
                sd = _m.sqrt(v) if v > 0 else 0.0
                if sd > 0:
                    recent_sharpes[sid] = m / sd * _m.sqrt(252)

        alloc = allocate(
            outputs=outputs,
            recent_sharpes=recent_sharpes,
            has_live_history=has_history,
            prior_shares=prior_strategy_shares,
            strategy_returns=strategy_returns,
        )
        prior_strategy_shares = dict(alloc.strategy_shares)
        prior_contributions = {
            sid: dict(alloc.contributions.get(sid, {})) for sid in strategy_ids
        }

        # Overlay (vol scale + DD breaker + shock detector).
        per_symbol_returns: dict[str, list[float]] = {}
        for sym in alloc.book_targets:
            per_symbol_returns[sym] = _daily_returns_window(provider, sym, asof, 60)
        overlay = apply_overlay(
            book_targets=alloc.book_targets,
            spy_realized_vol_60d=spy_vol,
            vix_implied=0.0,  # Phase A: skipped
            portfolio_daily_returns=book.daily_returns[-60:],
            per_symbol_daily_returns=per_symbol_returns,
            equity_curve=book.equity_curve,
            dd_breaker_currently_active=dd_breaker_active,
        )
        dd_breaker_active = overlay.dd_breaker_active

        # Rebalance trigger.
        # If freeze_days_remaining > 0, hold current weights; just MTM.
        if freeze_days_remaining > 0:
            target_weights = (
                {s: v / book.equity for s, v in book.positions.items()}
                if book.equity > 0
                else {}
            )
            freeze_days_remaining -= 1
        else:
            target_weights = overlay.final_weights

        # Need price for every target symbol. Build close_prices dict for the step.
        close_prices: dict[str, float] = {}
        # All targets:
        for sym in target_weights:
            px = _close_at(provider, sym, asof)
            if px is not None:
                close_prices[sym] = px
        # Plus current positions (for MTM of existing holdings we're selling out of):
        for sym in book.positions:
            if sym not in close_prices:
                px = _close_at(provider, sym, asof)
                if px is not None:
                    close_prices[sym] = px

        step = book.step(asof=asof, target_weights=target_weights, close_prices=close_prices)

        if overlay.shock_day_detected:
            freeze_days_remaining = overlay.freeze_rebalancing_until_idx

        record.append({
            "asof": asof.isoformat(),
            "equity": step.equity,
            "cash": step.cash,
            "daily_return": step.daily_return,
            "n_trades": len(step.trades),
            "exposure_scale": overlay.exposure_scale,
            "target_vol": overlay.target_vol,
            "forecast_vol": overlay.forecast_vol,
            "dd_breaker_active": overlay.dd_breaker_active,
            "shock_day": overlay.shock_day_detected,
            "strategy_shares": dict(alloc.strategy_shares),
            "n_positions": len(step.positions),
        })
        asof += timedelta(days=1)

    summary = book.summary()
    if spy_curve:
        spy_total = spy_curve[-1] / spy_curve[0] - 1.0
    else:
        spy_total = 0.0
    summary["spy_total_return"] = spy_total
    summary["alpha_vs_spy"] = summary.get("total_return", 0.0) - spy_total

    # Deflated Sharpe (Bailey & Lopez de Prado).
    # n_trials = number of strategies tested in the ensemble; each strategy
    # we shipped was effectively one configuration trial. As we add tuning
    # variants during Phase B/C, this number should grow — the user is
    # responsible for tracking that off-band; the default reflects the
    # ensemble size as a lower bound.
    sharpe = summary.get("sharpe", 0.0)
    n_trading_days = summary.get("n_trading_days", 0)
    if book.daily_returns and n_trading_days > 30:
        rs = book.daily_returns
        mean = sum(rs) / len(rs)
        var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
        # Variance of Sharpe ratio across trials (use the var of returns
        # as a proxy when there's no panel of trials; DSR docs note this
        # is a conservative approximation when the panel isn't available).
        # We pass var of the strategy's own daily returns × 252 as a
        # rough estimate of cross-trial Sharpe variance.
        variance_sharpe = max(var * 252, 1e-6)
        n_trials = max(1, len(strategy_ids))
        try:
            p = deflated_sharpe_ratio(
                observed_sharpe=sharpe,
                n_trials=n_trials,
                variance_sharpe=variance_sharpe,
                T=n_trading_days,
            )
            summary["deflated_sharpe_p_value"] = p
            summary["deflated_sharpe_n_trials"] = n_trials
        except Exception as exc:
            summary["deflated_sharpe_p_value"] = None
            summary["deflated_sharpe_error"] = str(exc)

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "equity_curve.json").open("w") as f:
            json.dump(record, f, indent=2)
        with (out_dir / "summary.json").open("w") as f:
            json.dump(summary, f, indent=2, default=str)
        with (out_dir / "spy_benchmark.json").open("w") as f:
            json.dump(
                [{"asof": rec["asof"], "spy_equity": eq} for rec, eq in zip(record, spy_curve)],
                f,
                indent=2,
            )
        with (out_dir / "trade_log.json").open("w") as f:
            json.dump([asdict(t) for t in book.trade_log], f, indent=2, default=str)

    return summary


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAEC v6 portfolio backtest.")
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument("--starting-cash", type=float, default=230_000.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    summary = run_backtest(
        start=args.start,
        end=args.end,
        starting_cash=args.starting_cash,
        out_dir=args.out,
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()

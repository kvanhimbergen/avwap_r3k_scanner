from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf

from anchors import anchored_vwap, anchor_swing_low
from config import cfg
from indicators import trend_strength_series

def market_regime_series(index_df: pd.DataFrame, chop_band_pct: float = 0.01) -> pd.Series:
    loc = anchor_swing_low(index_df, cfg.SWING_LOOKBACK)
    av = anchored_vwap(index_df, loc)
    dist = (index_df["Close"] - av) / av
    reg = pd.Series(index=index_df.index, dtype="object")
    reg[dist > chop_band_pct] = "Risk-On"
    reg[dist < -chop_band_pct] = "Risk-Off"
    reg[(dist >= -chop_band_pct) & (dist <= chop_band_pct)] = "Chop"
    return reg

def rolling_swing_avwap(df: pd.DataFrame) -> pd.Series:
    av = pd.Series(index=df.index, dtype=float)
    for i in range(cfg.SWING_LOOKBACK, len(df)):
        window = df.iloc[i-cfg.SWING_LOOKBACK:i+1]
        loc = df.index.get_loc(window["Low"].idxmin())
        av.iloc[i] = anchored_vwap(df.iloc[:i+1], loc).iloc[-1]
    return av

def _apply_slippage(price: float, direction: str, side: str, slippage_bps: float) -> float:
    if slippage_bps <= 0:
        return price

    bps = slippage_bps / 10_000.0
    side = side.lower()
    direction = direction.lower()

    if direction == "long":
        return price * (1 + bps) if side == "entry" else price * (1 - bps)

    # Short entry is a sell -> worse price is lower; exit is a buy -> worse price is higher.
    return price * (1 - bps) if side == "entry" else price * (1 + bps)

def _bucketize(series: pd.Series, bins: Iterable[float], labels: Iterable[str]) -> pd.Series:
    return pd.cut(series, bins=bins, labels=labels, include_lowest=True)

@dataclass
class BenchmarkResult:
    name: str
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe: float | float("nan")

def backtest_symbol(
    symbol: str,
    start: str = "2022-01-01",
    end: str | None = None,
    direction: str = "Long",
    max_hold: int = 20,
) -> pd.DataFrame | None:
    px = yf.download(
        symbol,
        start=start,
        end=end,
        progress=False,
        auto_adjust=getattr(cfg, "BACKTEST_AUTO_ADJUST", True),
    )
    idx = yf.download(
        cfg.INDEX,
        start=start,
        end=end,
        progress=False,
        auto_adjust=getattr(cfg, "BACKTEST_AUTO_ADJUST", True),
    )
    if px.empty or idx.empty or len(px) < 250:
        return None

    px.columns = [c.title() for c in px.columns]
    idx.columns = [c.title() for c in idx.columns]

    regimes = market_regime_series(idx).reindex(px.index).ffill()

    avwap = rolling_swing_avwap(px)
    trend_series = trend_strength_series(px).reindex(px.index)
    avwap_slope = avwap.diff(cfg.AVWAP_SLOPE_LOOKBACK) / cfg.AVWAP_SLOPE_LOOKBACK

    # signal
    if direction == "Long":
        signal = (px["Close"] > avwap) & (trend_series > float(getattr(cfg, "TREND_SCORE_MIN_LONG", 5.0)))
        exit_cond = (px["Close"] < avwap)
    else:
        signal = (px["Close"] < avwap) & (trend_series < float(getattr(cfg, "TREND_SCORE_MIN_SHORT", -5.0)))
        exit_cond = (px["Close"] > avwap)

    trades = []
    i = cfg.SWING_LOOKBACK + int(getattr(cfg, "TREND_SCORE_WARMUP", 120))

    while i < len(px) - 2:
        if not bool(signal.iloc[i]) or pd.isna(avwap.iloc[i]):
            i += 1
            continue

        entry_i = i + 1
        entry_date = px.index[entry_i]
        entry = float(px["Open"].iloc[entry_i])
        entry_av = float(avwap.iloc[i])
        if np.isnan(entry) or np.isnan(entry_av):
            i += 1
            continue

        # 1R proxy = distance to AVWAP at entry context (structural)
        r = max(abs(entry - entry_av), 0.01)

        exit_i = None
        last_i = min(entry_i + max_hold, len(px) - 1)

        for j in range(entry_i, last_i):
            if bool(exit_cond.iloc[j]):
                exit_i = min(j + 1, len(px) - 1)  # exit next open
                break

        if exit_i is None:
            exit_i = last_i

        exit_date = px.index[exit_i]
        exit_px = float(px["Open"].iloc[exit_i])

        if direction == "Long":
            r_mult = (exit_px - entry) / r
        else:
            r_mult = (entry - exit_px) / r

        trades.append({
            "Symbol": symbol,
            "Direction": direction,
            "EntryDate": entry_date,
            "Entry": entry,
            "ExitDate": exit_date,
            "Exit": exit_px,
            "R": r_mult,
            "RPerShare": r,
            "Regime": regimes.iloc[i] if pd.notna(regimes.iloc[i]) else "Unknown",
            "TrendStrength": float(trend_series.iloc[i]) if pd.notna(trend_series.iloc[i]) else np.nan,
            "AVWAPSlope": float(avwap_slope.iloc[i]) if pd.notna(avwap_slope.iloc[i]) else np.nan,
            "HoldDays": int((exit_date - entry_date).days),
        })

        i = exit_i

    return pd.DataFrame(trades)

def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()

    return (
        trades.groupby(["Direction", "Regime"])
        .agg(
            trades=("R", "count"),
            win_rate=("R", lambda x: float((x > 0).mean())),
            avg_R=("R", "mean"),
            med_R=("R", "median"),
            expectancy=("R", "mean"),
        )
        .reset_index()
        .sort_values(["Direction", "Regime"])
    )

def enhance_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()

    enhanced = trades.copy()
    enhanced["TrendBucket"] = _bucketize(
        enhanced["TrendStrength"],
        bins=[-np.inf, -10, -5, 0, 5, 10, np.inf],
        labels=["<-10", "-10:-5", "-5:0", "0:5", "5:10", ">10"],
    )
    enhanced["AVWAPSlopeBucket"] = _bucketize(
        enhanced["AVWAPSlope"],
        bins=[-np.inf, -0.2, -0.05, 0.0, 0.05, 0.2, np.inf],
        labels=["<-0.2", "-0.2:-0.05", "-0.05:0", "0:0.05", "0.05:0.2", ">0.2"],
    )
    return enhanced

def simulate_portfolio(
    trades: pd.DataFrame,
    initial_equity: float = 100_000.0,
    risk_pct: float = 0.01,
    max_concurrent: int = 5,
    slippage_bps: float = 2.5,
    commission_per_trade: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if trades is None or trades.empty:
        return pd.DataFrame(), pd.DataFrame(), {}

    trades = trades.sort_values("EntryDate").reset_index(drop=True).copy()
    trades["EntryDate"] = pd.to_datetime(trades["EntryDate"])
    trades["ExitDate"] = pd.to_datetime(trades["ExitDate"])

    equity = float(initial_equity)
    open_positions = []
    executed = []
    equity_curve = []
    skipped = 0

    def close_positions(up_to_date: pd.Timestamp):
        nonlocal equity
        still_open = []
        for pos in open_positions:
            if pos["ExitDate"] <= up_to_date:
                equity += pos["PnL"] - commission_per_trade
                equity_curve.append({"Date": pos["ExitDate"], "Equity": equity})
                executed.append(pos)
            else:
                still_open.append(pos)
        return still_open

    for _, trade in trades.iterrows():
        entry_date = trade["EntryDate"]
        open_positions = close_positions(entry_date)

        if len(open_positions) >= max_concurrent:
            skipped += 1
            continue

        r_per_share = float(trade.get("RPerShare", np.nan))
        if not math.isfinite(r_per_share) or r_per_share <= 0:
            skipped += 1
            continue

        risk_amount = equity * risk_pct
        shares = risk_amount / r_per_share

        entry_adj = _apply_slippage(trade["Entry"], trade["Direction"], "entry", slippage_bps)
        exit_adj = _apply_slippage(trade["Exit"], trade["Direction"], "exit", slippage_bps)

        if trade["Direction"].lower() == "long":
            pnl = (exit_adj - entry_adj) * shares
        else:
            pnl = (entry_adj - exit_adj) * shares

        executed_trade = trade.to_dict()
        executed_trade.update({
            "EquityAtEntry": equity,
            "RiskAmount": risk_amount,
            "Shares": shares,
            "EntryAdj": entry_adj,
            "ExitAdj": exit_adj,
            "PnL": pnl,
            "ReturnPct": pnl / equity if equity else 0.0,
        })

        open_positions.append(executed_trade)

    open_positions = close_positions(pd.Timestamp.max)

    executed_df = pd.DataFrame(executed)
    equity_curve_df = pd.DataFrame(equity_curve).sort_values("Date")

    meta = {
        "initial_equity": initial_equity,
        "ending_equity": equity,
        "skipped_trades": skipped,
        "max_concurrent": max_concurrent,
        "risk_pct": risk_pct,
        "slippage_bps": slippage_bps,
        "commission_per_trade": commission_per_trade,
    }

    return executed_df, equity_curve_df, meta

def portfolio_metrics(executed_trades: pd.DataFrame, equity_curve: pd.DataFrame) -> dict:
    if executed_trades is None or executed_trades.empty:
        return {}

    total_trades = len(executed_trades)
    wins = (executed_trades["PnL"] > 0).sum()
    losses = (executed_trades["PnL"] < 0).sum()
    avg_win = executed_trades.loc[executed_trades["PnL"] > 0, "PnL"].mean()
    avg_loss = executed_trades.loc[executed_trades["PnL"] < 0, "PnL"].mean()
    profit_factor = (
        executed_trades.loc[executed_trades["PnL"] > 0, "PnL"].sum()
        / abs(executed_trades.loc[executed_trades["PnL"] < 0, "PnL"].sum())
        if losses > 0 else np.nan
    )

    start_date = executed_trades["EntryDate"].min()
    end_date = executed_trades["ExitDate"].max()
    years = max((end_date - start_date).days / 365.25, 1e-6)
    equity_start = float(executed_trades["EquityAtEntry"].iloc[0])
    equity_end = float(equity_curve["Equity"].iloc[-1]) if not equity_curve.empty else equity_start
    cagr = (equity_end / equity_start) ** (1 / years) - 1

    if not equity_curve.empty:
        eq = equity_curve["Equity"]
        rolling_max = eq.cummax()
        drawdown = (eq - rolling_max) / rolling_max
        max_dd = drawdown.min()
    else:
        max_dd = 0.0

    returns = executed_trades["ReturnPct"].replace([np.inf, -np.inf], np.nan).dropna()
    ret_mean = returns.mean() if not returns.empty else 0.0
    ret_std = returns.std(ddof=0) if len(returns) > 1 else 0.0
    sharpe = (ret_mean / ret_std) * math.sqrt(len(returns)) if ret_std > 0 else np.nan
    downside = returns[returns < 0]
    downside_std = downside.std(ddof=0) if len(downside) > 1 else 0.0
    sortino = (ret_mean / downside_std) * math.sqrt(len(returns)) if downside_std > 0 else np.nan

    hold_days = executed_trades["HoldDays"].mean() if "HoldDays" in executed_trades else np.nan

    return {
        "total_trades": total_trades,
        "win_rate": wins / total_trades if total_trades else 0.0,
        "avg_win": float(avg_win) if math.isfinite(avg_win) else np.nan,
        "avg_loss": float(avg_loss) if math.isfinite(avg_loss) else np.nan,
        "profit_factor": float(profit_factor) if math.isfinite(profit_factor) else np.nan,
        "expectancy": float(executed_trades["ReturnPct"].mean()),
        "cagr": float(cagr),
        "max_drawdown": float(max_dd),
        "sharpe": float(sharpe) if math.isfinite(sharpe) else np.nan,
        "sortino": float(sortino) if math.isfinite(sortino) else np.nan,
        "average_hold_days": float(hold_days) if math.isfinite(hold_days) else np.nan,
        "equity_start": equity_start,
        "equity_end": equity_end,
    }

def bootstrap_trade_stats(executed_trades: pd.DataFrame, n_samples: int = 1000, seed: int = 7) -> pd.DataFrame:
    if executed_trades is None or executed_trades.empty:
        return pd.DataFrame()

    rng = np.random.default_rng(seed)
    returns = executed_trades["ReturnPct"].dropna().values
    if returns.size == 0:
        return pd.DataFrame()

    stats = []
    for _ in range(n_samples):
        sample = rng.choice(returns, size=len(returns), replace=True)
        stats.append({
            "mean_return": float(np.mean(sample)),
            "win_rate": float((sample > 0).mean()),
            "median_return": float(np.median(sample)),
        })

    return pd.DataFrame(stats)

def rolling_window_summary(trades: pd.DataFrame, window_months: int = 12, step_months: int = 3) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()

    trades = trades.copy()
    trades["EntryDate"] = pd.to_datetime(trades["EntryDate"])
    start = trades["EntryDate"].min().normalize()
    end = trades["EntryDate"].max().normalize()

    rows = []
    window = pd.DateOffset(months=window_months)
    step = pd.DateOffset(months=step_months)

    current = start
    while current + window <= end:
        window_end = current + window
        subset = trades[(trades["EntryDate"] >= current) & (trades["EntryDate"] < window_end)]
        rows.append({
            "window_start": current.date(),
            "window_end": window_end.date(),
            "trades": len(subset),
            "win_rate": float((subset["R"] > 0).mean()) if not subset.empty else np.nan,
            "avg_R": float(subset["R"].mean()) if not subset.empty else np.nan,
            "median_R": float(subset["R"].median()) if not subset.empty else np.nan,
        })
        current += step

    return pd.DataFrame(rows)

def buy_and_hold_metrics(
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    auto_adjust: bool = True,
) -> BenchmarkResult | None:
    prices = yf.download(
        symbol,
        start=start,
        end=end,
        progress=False,
        auto_adjust=auto_adjust,
    )
    if prices.empty:
        return None

    prices.columns = [c.title() for c in prices.columns]
    close = prices["Close"].dropna()
    if close.empty:
        return None

    total_return = close.iloc[-1] / close.iloc[0] - 1
    years = max((close.index[-1] - close.index[0]).days / 365.25, 1e-6)
    cagr = (close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1

    daily_returns = close.pct_change().dropna()
    if not daily_returns.empty:
        sharpe = (daily_returns.mean() / daily_returns.std(ddof=0)) * math.sqrt(252)
    else:
        sharpe = np.nan

    rolling_max = close.cummax()
    drawdown = (close - rolling_max) / rolling_max
    max_dd = drawdown.min() if not drawdown.empty else 0.0

    return BenchmarkResult(
        name=f"{symbol} Buy/Hold",
        total_return=float(total_return),
        cagr=float(cagr),
        max_drawdown=float(max_dd),
        sharpe=float(sharpe) if math.isfinite(sharpe) else np.nan,
    )

def randomized_baseline(
    trades: pd.DataFrame,
    seed: int = 7,
    slippage_bps: float = 2.5,
    commission_per_trade: float = 1.0,
    auto_adjust: bool = True,
) -> dict:
    if trades is None or trades.empty:
        return {}

    rng = np.random.default_rng(seed)
    results = []
    symbols = trades["Symbol"].unique().tolist()

    price_cache: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        px = yf.download(
            symbol,
            start=trades["EntryDate"].min(),
            end=trades["ExitDate"].max(),
            progress=False,
            auto_adjust=auto_adjust,
        )
        if px.empty:
            continue
        px.columns = [c.title() for c in px.columns]
        price_cache[symbol] = px

    for trade in trades.itertuples(index=False):
        px = price_cache.get(trade.Symbol)
        if px is None or px.empty:
            continue

        hold_days = int(trade.HoldDays) if hasattr(trade, "HoldDays") else 0
        if hold_days <= 0:
            continue

        valid_indices = np.arange(0, len(px) - hold_days - 1)
        if valid_indices.size == 0:
            continue

        entry_idx = rng.choice(valid_indices)
        exit_idx = entry_idx + hold_days

        entry_price = float(px["Open"].iloc[entry_idx])
        exit_price = float(px["Open"].iloc[exit_idx])

        entry_adj = _apply_slippage(entry_price, trade.Direction, "entry", slippage_bps)
        exit_adj = _apply_slippage(exit_price, trade.Direction, "exit", slippage_bps)

        if trade.Direction.lower() == "long":
            pnl = (exit_adj - entry_adj) - commission_per_trade
        else:
            pnl = (entry_adj - exit_adj) - commission_per_trade

        return_pct = pnl / entry_adj if entry_adj else 0.0
        results.append(return_pct)

    if not results:
        return {}

    results_array = np.array(results)
    return {
        "name": "Randomized Entry Baseline",
        "trades": int(len(results_array)),
        "mean_return": float(results_array.mean()),
        "median_return": float(np.median(results_array)),
        "win_rate": float((results_array > 0).mean()),
    }

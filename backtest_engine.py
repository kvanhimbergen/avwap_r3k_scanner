from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

import scan_engine
from config import cfg as default_cfg
from setup_context import load_setup_rules
from universe import load_universe

DEFAULT_OHLCV_PATH = Path("cache") / "ohlcv_history.parquet"
DEFAULT_OUTPUT_DIR = Path("backtests")

ENTRY_MODEL_NEXT_OPEN = "next_open"
ENTRY_MODEL_SAME_CLOSE = "same_close"

TRIM_PCT = 0.30


@dataclass
class BacktestResult:
    output_dir: Path
    trades_path: Path
    positions_path: Path
    equity_curve_path: Path
    summary_path: Path
    trades: pd.DataFrame
    positions: pd.DataFrame
    equity_curve: pd.DataFrame
    summary: dict


def load_ohlcv_history(data_path: Path) -> pd.DataFrame:
    if not data_path.exists():
        raise FileNotFoundError(f"OHLCV history not found at {data_path}")
    df = pd.read_parquet(data_path, engine="pyarrow")
    if df.empty:
        raise ValueError(f"OHLCV history is empty at {data_path}")
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None).dt.normalize()
    df["Ticker"] = df["Ticker"].astype(str).str.upper()
    df = df.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    df = df.set_index(["Ticker", "Date"]).sort_index()
    return df


def get_symbol_history(df: pd.DataFrame, symbol: str, end_dt: pd.Timestamp) -> pd.DataFrame:
    # df is indexed by [Ticker, Date] for speed and determinism
    symbol = str(symbol).upper()
    end_dt = pd.Timestamp(end_dt)
    try:
        out = df.loc[(symbol, slice(None, end_dt)), :]
    except KeyError:
        return pd.DataFrame()
    if out.empty:
        return pd.DataFrame()
    # return as a flat frame with Date as a column (matches prior behavior)
    out = out.reset_index(level=0, drop=True).reset_index()
    return out


def get_bar(df: pd.DataFrame, symbol: str, session_date: pd.Timestamp) -> dict | None:
    symbol = str(symbol).upper()
    session_date = pd.Timestamp(session_date)
    try:
        rec = df.loc[(symbol, session_date)]
    except KeyError:
        return None
    # If duplicates ever exist, take the first deterministically
    if isinstance(rec, pd.DataFrame):
        rec = rec.iloc[0]
    return {
        "Open": float(rec["Open"]),
        "High": float(rec["High"]),
        "Low": float(rec["Low"]),
        "Close": float(rec["Close"]),
    }


def _normalize_date(value: str | date | datetime | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.normalize()


def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, path)


def _atomic_write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def _round_series(series: pd.Series, decimals: int = 4) -> pd.Series:
    return series.round(decimals)


def _round_frame(df: pd.DataFrame, columns: Iterable[str], decimals: int = 4) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = _round_series(df[col], decimals=decimals)
    return df


def _direction_sign(direction: str) -> int:
    return -1 if direction.lower() == "short" else 1


def _scan_as_of(
    history: pd.DataFrame,
    symbols: list[str],
    sector_map: dict[str, str],
    as_of_dt: pd.Timestamp,
    scan_cfg,
    *,
    return_stats: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, int]]:
    scan_engine._ACTIVE_CFG = scan_cfg
    setup_rules = load_setup_rules()
    rows: list[dict] = []
    symbols_scanned = 0
    symbols_with_ohlcv_today = 0
    for symbol in symbols:
        sym_hist = get_symbol_history(history, symbol, as_of_dt)
        if sym_hist.empty:
            continue
        symbols_scanned += 1
        if (sym_hist["Date"] == as_of_dt).any():
            symbols_with_ohlcv_today += 1
        df = sym_hist.set_index("Date").sort_index()
        row = scan_engine.build_candidate_row(
            df,
            symbol,
            sector_map.get(symbol, "Unknown"),
            setup_rules,
            as_of_dt=as_of_dt,
            direction="Long",
        )
        if row:
            rows.append(row)
    candidates = scan_engine._build_candidates_dataframe(rows)
    if return_stats:
        return candidates, {
            "symbols_scanned": symbols_scanned,
            "symbols_with_ohlcv_today": symbols_with_ohlcv_today,
        }
    return candidates


def _validate_candidates(
    candidates: pd.DataFrame, *, strict_schema: bool
) -> tuple[pd.DataFrame, int]:
    if candidates.empty:
        return candidates, 0

    required_columns = ["Symbol", "Stop_Loss", "Target_R1", "Target_R2"]
    missing = [col for col in required_columns if col not in candidates.columns]
    if missing:
        if strict_schema:
            raise ValueError(f"Candidates missing required columns: {missing}")
        return candidates.iloc[0:0].copy(), 0

    working = candidates.copy()
    working["Symbol"] = working["Symbol"].astype(str).str.upper()
    numeric = working[["Stop_Loss", "Target_R1", "Target_R2"]].apply(
        pd.to_numeric, errors="coerce"
    )
    valid_mask = (
        working["Symbol"].notna()
        & working["Symbol"].str.len().gt(0)
        & numeric.notna().all(axis=1)
    )
    valid = working.loc[valid_mask].copy()
    for col in ["Stop_Loss", "Target_R1", "Target_R2"]:
        valid[col] = numeric.loc[valid_mask, col].astype(float)
    valid = valid.reindex(columns=candidates.columns)
    return valid, int(valid_mask.sum())


def run_backtest(
    cfg,
    start_date: str | date | datetime,
    end_date: str | date | datetime,
    *,
    universe_symbols: list[str] | None = None,
) -> BacktestResult:
    if getattr(cfg, "BACKTEST_UNIVERSE_ALLOW_NETWORK", False):
        raise ValueError("BACKTEST_UNIVERSE_ALLOW_NETWORK must be False for offline backtests.")

    entry_model = getattr(cfg, "BACKTEST_ENTRY_MODEL", ENTRY_MODEL_NEXT_OPEN)
    if entry_model not in (ENTRY_MODEL_NEXT_OPEN, ENTRY_MODEL_SAME_CLOSE):
        raise ValueError(f"Unsupported entry model: {entry_model}")

    verbose = bool(getattr(cfg, "BACKTEST_VERBOSE", False))
    debug_save_candidates = bool(getattr(cfg, "BACKTEST_DEBUG_SAVE_CANDIDATES", False))
    strict_schema = bool(getattr(cfg, "BACKTEST_STRICT_SCHEMA", False))

    max_hold_days = int(getattr(cfg, "BACKTEST_MAX_HOLD_DAYS", 5))
    initial_cash = float(
        getattr(cfg, "BACKTEST_INITIAL_CASH", getattr(cfg, "BACKTEST_INITIAL_EQUITY", 100_000.0))
    )

    output_dir = Path(getattr(cfg, "BACKTEST_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    history = load_ohlcv_history(Path(getattr(cfg, "BACKTEST_OHLCV_PATH", DEFAULT_OHLCV_PATH)))

    start_dt = _normalize_date(start_date)
    end_dt = _normalize_date(end_date)
    if start_dt > end_dt:
        raise ValueError("start_date must be <= end_date")

    dates = history.index.get_level_values("Date")
    trading_days = (
        pd.Series(dates)
        .dropna()
        .dt.normalize()
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    trading_days = [d for d in trading_days if start_dt <= d <= end_dt]

    if universe_symbols is None:
        universe = load_universe(allow_network=False)
        if universe.empty or "Ticker" not in universe.columns:
            raise ValueError("Universe snapshot missing or empty; cannot run backtest.")
        symbols = (
            universe["Ticker"].dropna().astype(str).str.upper().unique().tolist()
        )
        sector_map = {}
        if "Sector" in universe.columns:
            sector_map = {
                str(row["Ticker"]).upper(): str(row["Sector"])
                for _, row in universe.iterrows()
            }
    else:
        symbols = [str(sym).upper() for sym in universe_symbols]
        sector_map = {}

    symbols = sorted(dict.fromkeys(symbols))

    trades: list[dict] = []
    position_snapshots: list[dict] = []
    equity_curve: list[dict] = []
    closed_positions: list[dict] = []
    diagnostics_rows: list[dict] = []

    cash = initial_cash
    positions: dict[str, dict] = {}
    pending_entries: list[dict] = []
    next_position_id = 1

    for idx, session_date in enumerate(trading_days):
        session_date = pd.Timestamp(session_date)
        entries_placed_today = 0
        entries_filled_today = 0
        trades_fills_today = 0
        candidates_skipped_missing_next_open_bar = 0

        if entry_model == ENTRY_MODEL_NEXT_OPEN:
            ready = [p for p in pending_entries if p["entry_date"] == session_date]
            pending_entries = [p for p in pending_entries if p["entry_date"] != session_date]
            for entry in sorted(ready, key=lambda x: x["symbol"]):
                symbol = entry["symbol"]
                if symbol in positions:
                    continue
                bar = get_bar(history, symbol, session_date)
                if bar is None:
                    candidates_skipped_missing_next_open_bar += 1
                    continue
                entry_price = bar["Open"]
                qty = 1.0
                direction = entry["direction"]
                sign = _direction_sign(direction)
                cash -= sign * entry_price * qty
                position = {
                    "position_id": entry["position_id"],
                    "symbol": symbol,
                    "direction": direction,
                    "entry_date": session_date,
                    "entry_price": entry_price,
                    "qty": qty,
                    "remaining_qty": qty,
                    "stop": entry["stop"],
                    "r1": entry["r1"],
                    "r2": entry["r2"],
                    "hold_days": 0,
                    "r1_trimmed": False,
                }
                positions[symbol] = position
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": direction,
                        "fill_type": "entry",
                        "reason": "signal",
                        "price": entry_price,
                        "qty": qty,
                        "remaining_qty": qty,
                        "pnl": 0.0,
                        "position_id": entry["position_id"],
                        "hold_days": 0,
                    }
                )
                entries_filled_today += 1
                trades_fills_today += 1

        for symbol in sorted(list(positions.keys())):
            pos = positions[symbol]
            bar = get_bar(history, symbol, session_date)
            if bar is None:
                continue
            pos["hold_days"] += 1
            sign = _direction_sign(pos["direction"])

            stop_hit = bar["Low"] <= pos["stop"] if sign > 0 else bar["High"] >= pos["stop"]
            r1_hit = bar["High"] >= pos["r1"] if sign > 0 else bar["Low"] <= pos["r1"]
            r2_hit = bar["High"] >= pos["r2"] if sign > 0 else bar["Low"] <= pos["r2"]

            if stop_hit:
                exit_price = pos["stop"]
                qty = pos["remaining_qty"]
                pnl = sign * (exit_price - pos["entry_price"]) * qty
                cash += sign * exit_price * qty
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": pos["direction"],
                        "fill_type": "exit",
                        "reason": "stop",
                        "price": exit_price,
                        "qty": qty,
                        "remaining_qty": 0.0,
                        "pnl": pnl,
                        "position_id": pos["position_id"],
                        "hold_days": pos["hold_days"],
                    }
                )
                trades_fills_today += 1
                closed_positions.append(
                    {
                        "position_id": pos["position_id"],
                        "entry_date": pos["entry_date"],
                        "exit_date": session_date,
                        "pnl": pnl,
                        "hold_days": pos["hold_days"],
                    }
                )
                del positions[symbol]
                continue

            if r1_hit and not pos["r1_trimmed"]:
                trim_qty = pos["qty"] * TRIM_PCT
                trim_qty = min(trim_qty, pos["remaining_qty"])
                if trim_qty > 0:
                    trim_price = pos["r1"]
                    pnl = sign * (trim_price - pos["entry_price"]) * trim_qty
                    cash += sign * trim_price * trim_qty
                    pos["remaining_qty"] -= trim_qty
                    pos["r1_trimmed"] = True
                    trades.append(
                        {
                            "date": session_date.date().isoformat(),
                            "symbol": symbol,
                            "direction": pos["direction"],
                            "fill_type": "trim",
                            "reason": "target_r1",
                            "price": trim_price,
                            "qty": trim_qty,
                            "remaining_qty": pos["remaining_qty"],
                            "pnl": pnl,
                            "position_id": pos["position_id"],
                            "hold_days": pos["hold_days"],
                        }
                    )
                    trades_fills_today += 1

            if r2_hit and pos["remaining_qty"] > 0:
                exit_price = pos["r2"]
                qty = pos["remaining_qty"]
                pnl = sign * (exit_price - pos["entry_price"]) * qty
                cash += sign * exit_price * qty
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": pos["direction"],
                        "fill_type": "exit",
                        "reason": "target_r2",
                        "price": exit_price,
                        "qty": qty,
                        "remaining_qty": 0.0,
                        "pnl": pnl,
                        "position_id": pos["position_id"],
                        "hold_days": pos["hold_days"],
                    }
                )
                trades_fills_today += 1
                closed_positions.append(
                    {
                        "position_id": pos["position_id"],
                        "entry_date": pos["entry_date"],
                        "exit_date": session_date,
                        "pnl": pnl,
                        "hold_days": pos["hold_days"],
                    }
                )
                del positions[symbol]
                continue

            if pos["hold_days"] >= max_hold_days and pos["remaining_qty"] > 0:
                exit_price = bar["Close"]
                qty = pos["remaining_qty"]
                pnl = sign * (exit_price - pos["entry_price"]) * qty
                cash += sign * exit_price * qty
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": pos["direction"],
                        "fill_type": "exit",
                        "reason": "time_stop",
                        "price": exit_price,
                        "qty": qty,
                        "remaining_qty": 0.0,
                        "pnl": pnl,
                        "position_id": pos["position_id"],
                        "hold_days": pos["hold_days"],
                    }
                )
                trades_fills_today += 1
                closed_positions.append(
                    {
                        "position_id": pos["position_id"],
                        "entry_date": pos["entry_date"],
                        "exit_date": session_date,
                        "pnl": pnl,
                        "hold_days": pos["hold_days"],
                    }
                )
                del positions[symbol]

        candidates, scan_stats = _scan_as_of(
            history, symbols, sector_map, session_date, cfg, return_stats=True
        )
        if not candidates.empty and "Symbol" in candidates.columns:
            candidates = candidates.sort_values(["Symbol"]).reset_index(drop=True)

        if debug_save_candidates:
            candidates_snapshot = candidates
            if "Symbol" in candidates_snapshot.columns:
                candidates_snapshot = candidates_snapshot.sort_values(["Symbol"]).reset_index(
                    drop=True
                )
            candidates_snapshot = candidates_snapshot.reindex(columns=candidates.columns)
            snapshot_path = output_dir / "candidates" / f"{session_date.date().isoformat()}.csv"
            _atomic_write_csv(candidates_snapshot, snapshot_path)

        candidates_total = int(len(candidates))
        candidates, candidates_with_required_fields = _validate_candidates(
            candidates, strict_schema=strict_schema
        )

        for _, row in candidates.iterrows():
            symbol = str(row["Symbol"]).upper()
            if symbol in positions:
                continue
            if any(p["symbol"] == symbol for p in pending_entries):
                continue
            direction = str(row.get("Direction", "Long"))

            if entry_model == ENTRY_MODEL_SAME_CLOSE:
                bar = get_bar(history, symbol, session_date)
                if bar is None:
                    continue
                entry_price = bar["Close"]
                qty = 1.0
                sign = _direction_sign(direction)
                cash -= sign * entry_price * qty
                position = {
                    "position_id": next_position_id,
                    "symbol": symbol,
                    "direction": direction,
                    "entry_date": session_date,
                    "entry_price": entry_price,
                    "qty": qty,
                    "remaining_qty": qty,
                    "stop": float(row["Stop_Loss"]),
                    "r1": float(row["Target_R1"]),
                    "r2": float(row["Target_R2"]),
                    "hold_days": 0,
                    "r1_trimmed": False,
                }
                positions[symbol] = position
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": direction,
                        "fill_type": "entry",
                        "reason": "signal",
                        "price": entry_price,
                        "qty": qty,
                        "remaining_qty": qty,
                        "pnl": 0.0,
                        "position_id": next_position_id,
                        "hold_days": 0,
                    }
                )
                entries_placed_today += 1
                entries_filled_today += 1
                trades_fills_today += 1
                next_position_id += 1
            else:
                if idx + 1 >= len(trading_days):
                    continue
                pending_entries.append(
                    {
                        "entry_date": pd.Timestamp(trading_days[idx + 1]),
                        "symbol": symbol,
                        "direction": direction,
                        "stop": float(row["Stop_Loss"]),
                        "r1": float(row["Target_R1"]),
                        "r2": float(row["Target_R2"]),
                        "position_id": next_position_id,
                    }
                )
                entries_placed_today += 1
                next_position_id += 1

        positions_value = 0.0
        for symbol, pos in positions.items():
            sym_hist = get_symbol_history(history, symbol, session_date)
            if sym_hist.empty:
                continue
            last_close = float(sym_hist.iloc[-1]["Close"])
            sign = _direction_sign(pos["direction"])
            positions_value += sign * last_close * pos["remaining_qty"]
            position_snapshots.append(
                {
                    "date": session_date.date().isoformat(),
                    "symbol": symbol,
                    "direction": pos["direction"],
                    "entry_date": pos["entry_date"].date().isoformat(),
                    "entry_price": pos["entry_price"],
                    "qty": pos["qty"],
                    "remaining_qty": pos["remaining_qty"],
                    "stop_loss": pos["stop"],
                    "target_r1": pos["r1"],
                    "target_r2": pos["r2"],
                    "hold_days": pos["hold_days"],
                    "last_price": last_close,
                    "market_value": sign * last_close * pos["remaining_qty"],
                    "unrealized_pnl": sign * (last_close - pos["entry_price"]) * pos["remaining_qty"],
                    "position_id": pos["position_id"],
                }
            )

        equity = cash + positions_value
        equity_curve.append(
            {
                "date": session_date.date().isoformat(),
                "cash": cash,
                "positions_value": positions_value,
                "equity": equity,
                "open_positions": len(positions),
            }
        )
        diagnostics_rows.append(
            {
                "date": session_date.date().isoformat(),
                "universe_symbols": len(symbols),
                "symbols_with_ohlcv_today": scan_stats["symbols_with_ohlcv_today"],
                "symbols_scanned": scan_stats["symbols_scanned"],
                "candidates_total": candidates_total,
                "candidates_with_required_fields": candidates_with_required_fields,
                "candidates_skipped_missing_next_open_bar": candidates_skipped_missing_next_open_bar,
                "entries_placed": entries_placed_today,
                "entries_filled": entries_filled_today,
                "open_positions_end_of_day": len(positions),
                "trades_fills_today": trades_fills_today,
                "equity_end_of_day": round(equity, 4),
            }
        )
        if verbose:
            print(
                " | ".join(
                    [
                        f"{session_date.date().isoformat()}",
                        f"candidates={candidates_total}",
                        f"entries_filled={entries_filled_today}",
                        f"open_positions={len(positions)}",
                        f"equity={round(equity, 4)}",
                    ]
                )
            )

    trades_df = pd.DataFrame(trades)
    positions_df = pd.DataFrame(position_snapshots)
    equity_df = pd.DataFrame(equity_curve)

    trades_columns = [
        "date",
        "symbol",
        "direction",
        "fill_type",
        "reason",
        "price",
        "qty",
        "remaining_qty",
        "pnl",
        "position_id",
        "hold_days",
    ]
    positions_columns = [
        "date",
        "symbol",
        "direction",
        "entry_date",
        "entry_price",
        "qty",
        "remaining_qty",
        "stop_loss",
        "target_r1",
        "target_r2",
        "hold_days",
        "last_price",
        "market_value",
        "unrealized_pnl",
        "position_id",
    ]
    equity_columns = ["date", "cash", "positions_value", "equity", "open_positions"]

    if not trades_df.empty:
        trades_df = trades_df.reindex(columns=trades_columns)
        trades_df = trades_df.sort_values(["date", "symbol", "fill_type"]).reset_index(drop=True)
    else:
        trades_df = pd.DataFrame(columns=trades_columns)

    if not positions_df.empty:
        positions_df = positions_df.reindex(columns=positions_columns)
        positions_df = positions_df.sort_values(["date", "symbol"]).reset_index(drop=True)
    else:
        positions_df = pd.DataFrame(columns=positions_columns)

    if not equity_df.empty:
        equity_df = equity_df.reindex(columns=equity_columns)
        equity_df = equity_df.sort_values(["date"]).reset_index(drop=True)
    else:
        equity_df = pd.DataFrame(columns=equity_columns)

    trades_df = _round_frame(trades_df, ["price", "qty", "remaining_qty", "pnl"], decimals=4)
    positions_df = _round_frame(
        positions_df,
        [
            "entry_price",
            "qty",
            "remaining_qty",
            "stop_loss",
            "target_r1",
            "target_r2",
            "last_price",
            "market_value",
            "unrealized_pnl",
        ],
        decimals=4,
    )
    equity_df = _round_frame(equity_df, ["cash", "positions_value", "equity"], decimals=4)

    total_trades = int(trades_df[trades_df["fill_type"] == "entry"].shape[0])
    wins = 0
    avg_hold_days = 0.0
    if closed_positions:
        wins = sum(1 for pos in closed_positions if pos["pnl"] > 0)
        avg_hold_days = sum(pos["hold_days"] for pos in closed_positions) / len(closed_positions)
    win_rate = (wins / len(closed_positions)) if closed_positions else 0.0

    max_drawdown = 0.0
    if not equity_df.empty:
        running_max = equity_df["equity"].cummax()
        drawdowns = (equity_df["equity"] - running_max) / running_max
        max_drawdown = float(drawdowns.min())

    final_equity = float(equity_df["equity"].iloc[-1]) if not equity_df.empty else initial_cash
    total_return = (final_equity - initial_cash) / initial_cash if initial_cash else 0.0

    summary = {
        "start_date": start_dt.date().isoformat(),
        "end_date": end_dt.date().isoformat(),
        "initial_equity": round(initial_cash, 4),
        "final_equity": round(final_equity, 4),
        "total_return": round(total_return, 6),
        "total_trades": total_trades,
        "win_rate": round(win_rate, 6),
        "max_drawdown": round(max_drawdown, 6),
        "avg_hold_days": round(avg_hold_days, 4),
    }

    trades_path = output_dir / "trades.csv"
    positions_path = output_dir / "positions.csv"
    equity_curve_path = output_dir / "equity_curve.csv"
    summary_path = output_dir / "summary.json"
    diagnostics_path = output_dir / "scan_diagnostics.csv"

    _atomic_write_csv(trades_df, trades_path)
    _atomic_write_csv(positions_df, positions_path)
    _atomic_write_csv(equity_df, equity_curve_path)
    _atomic_write_json(summary, summary_path)
    diagnostics_df = pd.DataFrame(diagnostics_rows)
    diagnostics_columns = [
        "date",
        "universe_symbols",
        "symbols_with_ohlcv_today",
        "symbols_scanned",
        "candidates_total",
        "candidates_with_required_fields",
        "candidates_skipped_missing_next_open_bar",
        "entries_placed",
        "entries_filled",
        "open_positions_end_of_day",
        "trades_fills_today",
        "equity_end_of_day",
    ]
    if not diagnostics_df.empty:
        diagnostics_df = diagnostics_df.reindex(columns=diagnostics_columns)
        diagnostics_df = diagnostics_df.sort_values(["date"]).reset_index(drop=True)
    else:
        diagnostics_df = pd.DataFrame(columns=diagnostics_columns)
    _atomic_write_csv(diagnostics_df, diagnostics_path)

    return BacktestResult(
        output_dir=output_dir,
        trades_path=trades_path,
        positions_path=positions_path,
        equity_curve_path=equity_curve_path,
        summary_path=summary_path,
        trades=trades_df,
        positions=positions_df,
        equity_curve=equity_df,
        summary=summary,
    )


def run_backtest_default(
    start_date: str | date | datetime,
    end_date: str | date | datetime,
    *,
    universe_symbols: list[str] | None = None,
) -> BacktestResult:
    return run_backtest(default_cfg, start_date, end_date, universe_symbols=universe_symbols)

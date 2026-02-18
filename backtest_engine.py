from __future__ import annotations

import json
import math
import os
import platform
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from analytics import risk_attribution
from analytics import risk_attribution_rolling
from analytics import risk_attribution_summary
from analytics import risk_attribution_slack_summary
import scan_engine
from config import cfg as default_cfg
from setup_context import load_setup_rules
from universe import load_universe, load_universe_as_of
from provenance import (
    compute_config_hash,
    compute_data_hash,
    compute_run_id,
    git_sha,
    require_provenance_fields,
    validate_execution_mode,
)
from portfolio.risk_controls import (
    adjust_order_quantity,
    build_risk_controls,
    resolve_drawdown_guardrail,
    RiskControlResult,
    risk_modulation_enabled,
)

DEFAULT_OHLCV_PATH = Path("cache") / "ohlcv_history.parquet"
DEFAULT_OUTPUT_DIR = Path("backtests")

ENTRY_MODEL_NEXT_OPEN = "next_open"
ENTRY_MODEL_SAME_CLOSE = "same_close"

TRIM_PCT = 0.30
EPSILON = 1e-9


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
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.round(decimals)


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


def _cfg_value(cfg, name: str, fallback_name: str, default):
    if hasattr(cfg, name):
        return getattr(cfg, name)
    return getattr(cfg, fallback_name, default)


def _apply_slippage(price: float, *, bps: float, direction: str, is_entry: bool) -> float:
    sign = _direction_sign(direction)
    slip = bps / 10_000.0
    if is_entry:
        return price * (1 + slip * sign)
    return price * (1 - slip * sign)


def _marketable_limit_ok(
    *, ideal: float, slipped: float, direction: str, entry_limit_bps: float
) -> bool:
    sign = _direction_sign(direction)
    limit = entry_limit_bps / 10_000.0
    if sign > 0:
        return slipped <= ideal * (1 + limit + EPSILON)
    return slipped >= ideal * (1 - limit - EPSILON)


def _compute_positions_value(
    history: pd.DataFrame, positions: dict[str, dict], session_date: pd.Timestamp
) -> float:
    positions_value = 0.0
    for symbol, pos in positions.items():
        sym_hist = get_symbol_history(history, symbol, session_date)
        if sym_hist.empty:
            continue
        last_close = float(sym_hist.iloc[-1]["Close"])
        sign = _direction_sign(pos["direction"])
        positions_value += sign * last_close * pos["remaining_qty"]
    return positions_value


def _compute_gross_exposure(
    history: pd.DataFrame, positions: dict[str, dict], session_date: pd.Timestamp
) -> float:
    gross_value = 0.0
    for symbol, pos in positions.items():
        sym_hist = get_symbol_history(history, symbol, session_date)
        if sym_hist.empty:
            continue
        last_close = float(sym_hist.iloc[-1]["Close"])
        gross_value += abs(last_close * pos["remaining_qty"])
    return gross_value


def _risk_per_share(entry_price: float, stop: float, direction: str) -> float:
    sign = _direction_sign(direction)
    return max(sign * (entry_price - stop), 0.01)


def _compute_correlation_penalty(
    *,
    candidate_symbol: str,
    positions: dict[str, dict],
    history: pd.DataFrame,
    session_date: pd.Timestamp,
    cfg,
) -> float:
    """Compute correlation penalty for a candidate relative to open positions.

    Returns 0.0 on any failure (fail-open) or when the feature is disabled.
    """
    if not getattr(cfg, "CORRELATION_AWARE_SIZING_ENABLED", False):
        return 0.0
    if not positions:
        return 0.0
    try:
        from analytics.correlation_matrix import compute_rolling_correlation
        from execution_v2.correlation_sizing import correlation_penalty as _corr_pen

        open_syms = list(positions.keys())
        all_syms = open_syms + [candidate_symbol]
        lookback = getattr(cfg, "CORRELATION_LOOKBACK_DAYS", 60)

        # Build OHLCV slice from history for all_syms
        if isinstance(history.index, pd.MultiIndex):
            df = history.reset_index()
        else:
            df = history.copy()

        # Normalise column names
        col_map = {}
        for c in df.columns:
            cl = str(c).lower()
            if cl == "date":
                col_map[c] = "Date"
            elif cl == "symbol":
                col_map[c] = "Symbol"
            elif cl == "close":
                col_map[c] = "Close"
        df = df.rename(columns=col_map)

        corr_matrix = compute_rolling_correlation(df, all_syms, lookback_days=lookback)
        if corr_matrix.empty:
            return 0.0

        threshold = getattr(cfg, "CORRELATION_PENALTY_THRESHOLD", 0.6)
        return _corr_pen(candidate_symbol, open_syms, corr_matrix, threshold=threshold)
    except Exception as exc:
        print(f"WARN: correlation penalty failed for {candidate_symbol}: {exc}")
        return 0.0


def _check_backtest_sector_cap(
    *,
    candidate_symbol: str,
    positions: dict[str, dict],
    sector_map: dict[str, str],
    cfg,
    gross_exposure: float,
) -> tuple[bool, str]:
    """Check sector cap for backtest entries. Returns (allowed, reason)."""
    if not getattr(cfg, "CORRELATION_AWARE_SIZING_ENABLED", False):
        return True, ""
    if not sector_map:
        return True, ""
    cand_sector = sector_map.get(candidate_symbol, "")
    if not cand_sector:
        return True, ""
    try:
        from execution_v2.correlation_sizing import check_sector_cap

        open_pos_dicts = [
            {"symbol": sym, "notional": abs(pos.get("qty", 0.0) * pos.get("entry_price", 0.0))}
            for sym, pos in positions.items()
        ]
        max_sector_pct = getattr(cfg, "MAX_SECTOR_EXPOSURE_PCT", 0.3)
        return check_sector_cap(
            candidate_sector=cand_sector,
            open_positions=open_pos_dicts,
            sector_map=sector_map,
            max_sector_pct=max_sector_pct,
            gross_exposure=gross_exposure,
        )
    except Exception as exc:
        print(f"WARN: sector cap check failed for {candidate_symbol}: {exc}")
        return True, ""


def _get_run_id(scan_cfg) -> str | None:
    for attr in ("RUN_ID", "BACKTEST_RUN_ID"):
        if hasattr(scan_cfg, attr):
            value = getattr(scan_cfg, attr)
            if value:
                return str(value)
    return None


def _guardrail_violation(name: str, current: float | int | str, limit: float | int | str, run_id: str | None) -> None:
    run_id_value = run_id or "n/a"
    raise RuntimeError(
        f"Guardrail {name} violated: current={current} limit={limit} run_id={run_id_value}"
    )


def _kill_switch_active(scan_cfg, session_date: pd.Timestamp) -> bool:
    if bool(getattr(scan_cfg, "BACKTEST_KILL_SWITCH", False)):
        return True
    start_date = getattr(scan_cfg, "BACKTEST_KILL_SWITCH_START_DATE", None)
    if start_date:
        start_dt = _normalize_date(start_date)
        return pd.Timestamp(session_date).normalize() >= start_dt
    return False


def _enforce_entry_guardrails(
    *,
    scan_cfg,
    session_date: pd.Timestamp,
    symbol: str,
    entries_filled_today: int,
    unique_symbols_today: set[str],
    positions: dict[str, dict],
    equity_before: float,
    gross_exposure: float,
    notional: float,
    trade_risk: float,
    effective_max_positions: int | None = None,
    effective_max_gross_exposure_abs: float | None = None,
    effective_max_gross_exposure_pct: float | None = None,
) -> None:
    run_id = _get_run_id(scan_cfg)

    if _kill_switch_active(scan_cfg, session_date):
        _guardrail_violation("kill_switch", True, False, run_id)

    base_max_positions = int(_cfg_value(scan_cfg, "BACKTEST_MAX_POSITIONS", "BACKTEST_MAX_CONCURRENT", 5))
    max_positions = base_max_positions
    if effective_max_positions is not None:
        max_positions = min(base_max_positions, int(effective_max_positions))
    if len(positions) >= max_positions:
        _guardrail_violation("max_concurrent_positions", len(positions) + 1, max_positions, run_id)

    max_new_entries = int(getattr(scan_cfg, "BACKTEST_MAX_NEW_ENTRIES_PER_DAY", 10_000))
    if entries_filled_today + 1 > max_new_entries:
        _guardrail_violation(
            "max_new_entries_per_day", entries_filled_today + 1, max_new_entries, run_id
        )

    max_unique_symbols = int(getattr(scan_cfg, "BACKTEST_MAX_UNIQUE_SYMBOLS_PER_DAY", 10_000))
    projected_unique = len(unique_symbols_today) + (0 if symbol in unique_symbols_today else 1)
    if projected_unique > max_unique_symbols:
        _guardrail_violation(
            "max_unique_symbols_per_day", projected_unique, max_unique_symbols, run_id
        )

    max_risk_abs = float(getattr(scan_cfg, "BACKTEST_MAX_RISK_PER_TRADE_DOLLARS", 1_000_000.0))
    if trade_risk > max_risk_abs + EPSILON:
        _guardrail_violation("max_risk_per_trade_abs", round(trade_risk, 6), max_risk_abs, run_id)

    base_max_gross_exposure_pct = float(getattr(scan_cfg, "BACKTEST_MAX_GROSS_EXPOSURE_PCT", 1.0))
    max_gross_exposure_pct = base_max_gross_exposure_pct
    if effective_max_gross_exposure_pct is not None:
        max_gross_exposure_pct = min(base_max_gross_exposure_pct, float(effective_max_gross_exposure_pct))
    projected_gross = gross_exposure + abs(notional)
    if equity_before > 0 and (
        projected_gross / equity_before > max_gross_exposure_pct + EPSILON
    ):
        _guardrail_violation(
            "max_gross_exposure_pct",
            round(projected_gross / equity_before, 6),
            max_gross_exposure_pct,
            run_id,
        )

    base_max_gross_exposure_abs = float(
        getattr(scan_cfg, "BACKTEST_MAX_GROSS_EXPOSURE_DOLLARS", 1_000_000.0)
    )
    max_gross_exposure_abs = base_max_gross_exposure_abs
    if effective_max_gross_exposure_abs is not None:
        max_gross_exposure_abs = min(base_max_gross_exposure_abs, float(effective_max_gross_exposure_abs))
    if projected_gross > max_gross_exposure_abs + EPSILON:
        _guardrail_violation(
            "max_gross_exposure_abs", round(projected_gross, 6), max_gross_exposure_abs, run_id
        )


def _extension_high_from_candidate(row: pd.Series) -> bool | None:
    for key in ("Extension_High", "Setup_Extension_State", "Extension_State"):
        if key in row and pd.notna(row.get(key)):
            val = row.get(key)
            if isinstance(val, (int, float)):
                return bool(val)
            return "extend" in str(val).lower()
    return None

def _scan_as_of(
    history: pd.DataFrame,
    symbols: list[str],
    sector_map: dict[str, str],
    as_of_dt: pd.Timestamp,
    scan_cfg,
    *,
    return_stats: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, int]]:
    # Phase 2: Feature store read-back optimization (placeholder).
    # When enabled, could read pre-computed features instead of recomputing.
    # Currently a no-op — full candidate computation via build_candidate_row()
    # is required because feature store lacks quality gates, stops, and targets.
    if getattr(scan_cfg, "BACKTEST_USE_FEATURE_STORE", False):
        pass  # Future: read from feature store, fall back to inline below

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
        # Ensure unique session bars per symbol; duplicates break anchor index lookups
        if not df.index.is_unique:
            df = df[~df.index.duplicated(keep="first")]
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

    if getattr(scan_cfg, "CROSS_SECTIONAL_ENABLED", False) and not candidates.empty:
        from analytics.cross_sectional import apply_cross_sectional_scoring
        import numpy as np
        features = getattr(scan_cfg, "CROSS_SECTIONAL_FEATURES", ["TrendScore", "Entry_DistPct", "AVWAP_Slope"])
        top_decile = float(getattr(scan_cfg, "CROSS_SECTIONAL_TOP_DECILE", 0.1))
        hard_floor = float(getattr(scan_cfg, "CROSS_SECTIONAL_HARD_FLOOR_TREND_SCORE", 5.0))
        candidates = apply_cross_sectional_scoring(
            candidates, features=features, top_decile=top_decile, hard_floor_trend=hard_floor,
        )
        candidates["SchemaVersion"] = 2
    else:
        import numpy as np
        for col in ("TrendScore_Zscore", "TrendScore_Pctile", "DistPct_Zscore", "Composite_Rank"):
            if col not in candidates.columns:
                candidates[col] = np.nan

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
    parameters_used: dict | None = None,
    execution_mode: str = "single",
    write_run_meta: bool = True,
) -> BacktestResult:
    if getattr(cfg, "BACKTEST_UNIVERSE_ALLOW_NETWORK", False):
        raise ValueError("BACKTEST_UNIVERSE_ALLOW_NETWORK must be False for offline backtests.")

    validate_execution_mode(execution_mode)
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
    risk_per_trade_pct = float(_cfg_value(cfg, "BACKTEST_RISK_PER_TRADE_PCT", "BACKTEST_RISK_PCT", 0.01))
    min_dollar_position = float(getattr(cfg, "BACKTEST_MIN_DOLLAR_POSITION", 0.0))
    slippage_bps = float(getattr(cfg, "BACKTEST_SLIPPAGE_BPS", 0.0))
    entry_limit_bps = float(getattr(cfg, "BACKTEST_ENTRY_LIMIT_BPS", slippage_bps))
    extension_thresh = float(getattr(cfg, "BACKTEST_EXTENSION_THRESH", 0.03))
    invalidation_stop_buffer_pct = float(
        getattr(cfg, "BACKTEST_INVALIDATION_STOP_BUFFER_PCT", 0.0)
    )
    max_positions = int(_cfg_value(cfg, "BACKTEST_MAX_POSITIONS", "BACKTEST_MAX_CONCURRENT", 5))
    max_gross_exposure_pct = float(getattr(cfg, "BACKTEST_MAX_GROSS_EXPOSURE_PCT", 1.0))
    max_gross_exposure_abs = float(getattr(cfg, "BACKTEST_MAX_GROSS_EXPOSURE_DOLLARS", 1_000_000.0))

    repo_root = Path(getattr(cfg, "BACKTEST_REPO_ROOT", ".")).resolve()
    risk_controls_enabled = risk_modulation_enabled()
    drawdown_value, drawdown_threshold, _ = resolve_drawdown_guardrail()
    risk_controls_cache: dict[str, RiskControlResult] = {}

    def _resolve_risk_controls(date_ny: str) -> RiskControlResult | None:
        if not risk_controls_enabled:
            return None
        cached = risk_controls_cache.get(date_ny)
        if cached is not None:
            return cached
        result = build_risk_controls(
            ny_date=date_ny,
            repo_root=repo_root,
            base_max_positions=max_positions,
            base_max_gross_exposure=max_gross_exposure_abs,
            base_per_position_cap=None,
            drawdown=drawdown_value,
            max_drawdown_pct_block=drawdown_threshold,
        )
        risk_controls_cache[date_ny] = result
        return result

    dynamic_exposure_enabled = bool(getattr(cfg, "DYNAMIC_EXPOSURE_ENABLED", False))
    target_portfolio_vol = float(getattr(cfg, "TARGET_PORTFOLIO_VOL", 0.15))
    exposure_ceiling = float(getattr(cfg, "MAX_GROSS_EXPOSURE_CEILING", 1.0))
    exposure_floor = float(getattr(cfg, "MIN_GROSS_EXPOSURE_FLOOR", 0.2))
    vol_lookback_days = int(getattr(cfg, "PORTFOLIO_VOL_LOOKBACK_DAYS", 20))

    def _compute_dynamic_exposure_pct() -> float | None:
        if not dynamic_exposure_enabled:
            return None
        if len(equity_curve) < 2:
            return None
        from portfolio.dynamic_exposure import (
            compute_realized_portfolio_vol,
            compute_target_exposure,
        )
        equities = [row["equity"] for row in equity_curve]
        daily_returns = [
            (equities[i] - equities[i - 1]) / equities[i - 1]
            for i in range(1, len(equities))
            if equities[i - 1] > 0
        ]
        realized_vol = compute_realized_portfolio_vol(daily_returns, vol_lookback_days)
        result = compute_target_exposure(
            realized_vol,
            target_portfolio_vol,
            1.0,
            floor=exposure_floor,
            ceiling=exposure_ceiling,
        )
        return result.target_exposure

    output_dir = Path(getattr(cfg, "BACKTEST_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    data_path = Path(getattr(cfg, "BACKTEST_OHLCV_PATH", DEFAULT_OHLCV_PATH))
    history = load_ohlcv_history(data_path)

    start_dt = _normalize_date(start_date)
    end_dt = _normalize_date(end_date)
    if start_dt > end_dt:
        raise ValueError("start_date must be <= end_date")

    if parameters_used is None:
        parameters_used = {
            "start_date": start_dt.date().isoformat(),
            "end_date": end_dt.date().isoformat(),
            "entry_model": entry_model,
            "slippage_bps": slippage_bps,
            "entry_limit_bps": entry_limit_bps,
            "risk_per_trade_pct": risk_per_trade_pct,
            "max_positions": max_positions,
            "max_gross_exposure_pct": max_gross_exposure_pct,
            "stop_buffer": invalidation_stop_buffer_pct,
            "extension_thresh": extension_thresh,
            "invalidation_stop_buffer_pct": invalidation_stop_buffer_pct,
        }
    else:
        parameters_used = dict(parameters_used)

    git_sha_value = git_sha()
    config_hash = compute_config_hash(cfg)
    data_hash = compute_data_hash(data_path)
    run_id = compute_run_id(
        git_sha_value,
        config_hash,
        data_hash,
        execution_mode,
        parameters_used,
    )
    cfg.BACKTEST_RUN_ID = run_id

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

    use_dated_universe = bool(
        getattr(cfg, "BACKTEST_USE_DATED_UNIVERSE_SNAPSHOTS", False)
    )
    constituency_source = None

    # Phase 7: Load corporate actions for delisting detection
    corporate_actions_list = []
    corporate_actions_hash_value = None
    try:
        ca_path = Path(getattr(cfg, "BACKTEST_CORPORATE_ACTIONS_PATH", "universe/corporate_actions.csv"))
        if ca_path.exists():
            from universe.corporate_actions import get_delistings, load_corporate_actions
            corporate_actions_list = load_corporate_actions(ca_path)
            if corporate_actions_list:
                import hashlib as _hashlib
                corporate_actions_hash_value = _hashlib.sha256(
                    ca_path.read_bytes()
                ).hexdigest()
    except Exception as _ca_err:
        import logging as _logging
        _logging.getLogger(__name__).warning("Failed to load corporate actions: %s", _ca_err)

    # Phase 7: Load earnings calendar for point-in-time filtering
    earnings_calendar_df = None
    try:
        pit_path = Path(getattr(cfg, "BACKTEST_POINT_IN_TIME_EARNINGS_PATH", "universe/earnings_calendar.parquet"))
        if pit_path.exists():
            from universe.point_in_time_earnings import load_earnings_calendar
            earnings_calendar_df = load_earnings_calendar(pit_path)
            if earnings_calendar_df.empty:
                earnings_calendar_df = None
    except Exception:
        pass

    def _load_universe_for_date(session_date_str: str | None = None):
        """Load universe symbols and sector map, optionally for a specific date."""
        nonlocal constituency_source
        if universe_symbols is not None:
            return [str(sym).upper() for sym in universe_symbols], {}

        if use_dated_universe and session_date_str is not None:
            u = load_universe_as_of(session_date_str)
            constituency_source = getattr(
                cfg, "BACKTEST_HISTORICAL_CONSTITUENCY_PATH", "universe/historical"
            )
        else:
            u = load_universe(allow_network=False)
            constituency_source = "static"

        if u.empty or "Ticker" not in u.columns:
            raise ValueError("Universe snapshot missing or empty; cannot run backtest.")
        syms = u["Ticker"].dropna().astype(str).str.upper().unique().tolist()
        smap = {}
        if "Sector" in u.columns:
            smap = {
                str(row["Ticker"]).upper(): str(row["Sector"])
                for _, row in u.iterrows()
            }
        return sorted(dict.fromkeys(syms)), smap

    # Initial universe load (static mode or first pass)
    symbols, sector_map = _load_universe_for_date()

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
        symbols_traded_today: set[str] = set()
        trades_fills_today = 0
        candidates_skipped_missing_next_open_bar = 0
        entries_skipped_max_positions = 0
        entries_skipped_cash = 0
        entries_skipped_gross_exposure = 0
        entries_skipped_size_zero = 0
        entries_missed_limit = 0
        invalidations_today = 0
        stops_today = 0
        targets_r1_today = 0
        targets_r2_today = 0

        # Phase 7: Reload universe per-day if using dated constituency
        if use_dated_universe and universe_symbols is None:
            symbols, sector_map = _load_universe_for_date(
                session_date.date().isoformat()
            )

        # Phase 7: Force-exit positions in delisted symbols
        if corporate_actions_list:
            delisted_today = set(get_delistings(
                corporate_actions_list,
                as_of_date=session_date.date().isoformat(),
            ))
            for symbol in sorted(list(positions.keys())):
                if symbol not in delisted_today:
                    continue
                pos = positions[symbol]
                bar = get_bar(history, symbol, session_date)
                if bar is None:
                    # No price data — use last known entry price as exit
                    exit_price = pos["entry_price"]
                else:
                    exit_price = bar["Close"]
                qty = pos["remaining_qty"]
                if qty <= 0:
                    continue
                sign = _direction_sign(pos["direction"])
                equity_before = cash + _compute_positions_value(history, positions, session_date)
                pnl = sign * (exit_price - pos["entry_price"]) * qty
                cash += sign * exit_price * qty
                pos["remaining_qty"] = 0.0
                pos["realized_pnl"] += pnl
                equity_after = cash + _compute_positions_value(history, positions, session_date)
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": pos["direction"],
                        "fill_type": "exit",
                        "reason": "delisting",
                        "entry_reason": None,
                        "exit_reason": "delisting",
                        "price": exit_price,
                        "qty": qty,
                        "remaining_qty": 0.0,
                        "pnl": pnl,
                        "notional": exit_price * qty,
                        "slippage_bps": 0.0,
                        "ideal_fill_price": exit_price,
                        "slippage_actual_bps": 0.0,
                        "equity_before": equity_before,
                        "equity_after": equity_after,
                        "position_id": pos.get("position_id"),
                        "hold_days": pos["hold_days"],
                        "mae": sign * (pos["mae_price"] - pos["entry_price"]) * pos["initial_qty"],
                        "mfe": sign * (pos["mfe_price"] - pos["entry_price"]) * pos["initial_qty"],
                    }
                )
                del positions[symbol]

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
                ideal_price = bar["Open"]
                direction = entry["direction"]
                entry_price = _apply_slippage(
                    ideal_price, bps=slippage_bps, direction=direction, is_entry=True
                )
                if not _marketable_limit_ok(
                    ideal=ideal_price,
                    slipped=entry_price,
                    direction=direction,
                    entry_limit_bps=entry_limit_bps,
                ):
                    entries_missed_limit += 1
                    continue
                # Phase 5: Sector cap check
                gross_exposure = _compute_gross_exposure(history, positions, session_date)
                sector_allowed, sector_reason = _check_backtest_sector_cap(
                    candidate_symbol=symbol,
                    positions=positions,
                    sector_map=sector_map,
                    cfg=cfg,
                    gross_exposure=gross_exposure,
                )
                if not sector_allowed:
                    continue

                # Phase 5: Correlation penalty
                corr_penalty_val = _compute_correlation_penalty(
                    candidate_symbol=symbol,
                    positions=positions,
                    history=history,
                    session_date=session_date,
                    cfg=cfg,
                )

                equity_before = cash + _compute_positions_value(history, positions, session_date)
                risk_per_share = _risk_per_share(entry_price, entry["stop"], direction)
                dollar_risk = equity_before * risk_per_trade_pct * (1.0 - corr_penalty_val)
                base_qty = math.floor(dollar_risk / risk_per_share)
                if base_qty < 1:
                    entries_skipped_size_zero += 1
                    continue
                base_notional = entry_price * base_qty
                if base_notional < min_dollar_position:
                    entries_skipped_size_zero += 1
                    continue
                if _direction_sign(direction) > 0 and base_notional > cash + EPSILON:
                    entries_skipped_cash += 1
                    continue
                base_trade_risk = risk_per_share * base_qty
                risk_controls_result = _resolve_risk_controls(session_date.date().isoformat())
                effective_max_positions = None
                effective_max_gross_exposure_abs = None
                if risk_controls_result is not None:
                    rc = risk_controls_result.controls
                    if rc.max_positions is not None:
                        effective_max_positions = int(rc.max_positions)
                    if rc.max_gross_exposure is not None:
                        effective_max_gross_exposure_abs = float(rc.max_gross_exposure)

                _enforce_entry_guardrails(
                    scan_cfg=cfg,
                    session_date=session_date,
                    symbol=symbol,
                    entries_filled_today=entries_filled_today,
                    unique_symbols_today=symbols_traded_today,
                    positions=positions,
                    equity_before=equity_before,
                    gross_exposure=gross_exposure,
                    notional=base_notional,
                    trade_risk=base_trade_risk,
                    effective_max_positions=effective_max_positions,
                    effective_max_gross_exposure_abs=effective_max_gross_exposure_abs,
                    effective_max_gross_exposure_pct=_compute_dynamic_exposure_pct(),
                )
                qty = base_qty
                if risk_controls_result is not None:
                    min_qty = None
                    if min_dollar_position > 0:
                        min_qty = int(math.ceil(min_dollar_position / entry_price))
                    qty = adjust_order_quantity(
                        base_qty=base_qty,
                        price=entry_price,
                        account_equity=equity_before,
                        risk_controls=risk_controls_result.controls,
                        gross_exposure=gross_exposure,
                        min_qty=min_qty,
                    )
                    if risk_attribution.attribution_write_enabled():
                        try:
                            throttle = risk_controls_result.throttle or {}
                            throttle_regime_label = throttle.get("regime_label")
                            throttle_policy_ref = risk_attribution.resolve_throttle_policy_reference(
                                repo_root=repo_root,
                                ny_date=session_date.date().isoformat(),
                                source=risk_controls_result.source,
                            )
                            event = risk_attribution.build_attribution_event(
                                date_ny=session_date.date().isoformat(),
                                symbol=symbol,
                                baseline_qty=base_qty,
                                modulated_qty=qty,
                                price=entry_price,
                                account_equity=equity_before,
                                gross_exposure=gross_exposure,
                                risk_controls=risk_controls_result.controls,
                                risk_control_reasons=risk_controls_result.reasons,
                                throttle_source=risk_controls_result.source,
                                throttle_regime_label=throttle_regime_label,
                                throttle_policy_ref=throttle_policy_ref,
                                drawdown=drawdown_value,
                                drawdown_threshold=drawdown_threshold,
                                min_qty=min_qty,
                                source="backtest_engine",
                                correlation_penalty=corr_penalty_val,
                            )
                            risk_attribution.write_attribution_event(event)
                        except Exception as exc:
                            print(f"WARN: risk attribution write failed for {symbol}: {exc}")
                notional = entry_price * qty
                trade_risk = risk_per_share * qty
                sign = _direction_sign(direction)
                cash -= sign * entry_price * qty
                sym_hist = get_symbol_history(history, symbol, session_date)
                prior_close = None
                if len(sym_hist) >= 2:
                    prior_close = float(sym_hist.iloc[-2]["Close"])
                position = {
                    "position_id": entry["position_id"],
                    "symbol": symbol,
                    "direction": direction,
                    "entry_date": session_date,
                    "entry_price": entry_price,
                    "qty": float(qty),
                    "initial_qty": float(qty),
                    "remaining_qty": float(qty),
                    "stop": entry["stop"],
                    "r1": entry["r1"],
                    "r2": entry["r2"],
                    "hold_days": 0,
                    "r1_trimmed": False,
                    "entry_level": entry["entry_level"],
                    "extension_high": entry["extension_high"],
                    "avwap_reclaim_failed": entry["avwap_reclaim_failed"],
                    "realized_pnl": 0.0,
                    "mae_price": entry_price,
                    "mfe_price": entry_price,
                    "prior_close": prior_close,
                }
                positions[symbol] = position
                equity_after = cash + _compute_positions_value(history, positions, session_date)
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": direction,
                        "fill_type": "entry",
                        "reason": "signal",
                        "entry_reason": entry["entry_reason"],
                        "exit_reason": None,
                        "price": entry_price,
                        "qty": qty,
                        "remaining_qty": qty,
                        "pnl": 0.0,
                        "notional": notional,
                        "slippage_bps": slippage_bps,
                        "ideal_fill_price": ideal_price,
                        "slippage_actual_bps": slippage_bps,
                        "equity_before": equity_before,
                        "equity_after": equity_after,
                        "position_id": entry["position_id"],
                        "hold_days": 0,
                        "mae": None,
                        "mfe": None,
                    }
                )
                entries_filled_today += 1
                trades_fills_today += 1
                symbols_traded_today.add(symbol)

        for symbol in sorted(list(positions.keys())):
            pos = positions[symbol]
            bar = get_bar(history, symbol, session_date)
            if bar is None:
                continue
            pos["hold_days"] += 1
            sign = _direction_sign(pos["direction"])

            if sign > 0:
                pos["mfe_price"] = max(pos["mfe_price"], bar["High"])
                pos["mae_price"] = min(pos["mae_price"], bar["Low"])
            else:
                pos["mfe_price"] = min(pos["mfe_price"], bar["Low"])
                pos["mae_price"] = max(pos["mae_price"], bar["High"])

            stop_hit = bar["Low"] <= pos["stop"] if sign > 0 else bar["High"] >= pos["stop"]
            r1_hit = bar["High"] >= pos["r1"] if sign > 0 else bar["Low"] <= pos["r1"]
            r2_hit = bar["High"] >= pos["r2"] if sign > 0 else bar["Low"] <= pos["r2"]

            rejection_bar = bar["Close"] < bar["Open"] and (
                (bar["High"] - bar["Close"]) / (bar["High"] - bar["Low"] + EPSILON)
            ) > 0.6
            momentum_weakening = (
                pos["prior_close"] is not None
                and bar["Close"] <= pos["prior_close"] + EPSILON
            )
            # Proxy-only trim logic: extension condition + rejection/weak momentum on daily OHLC.
            extension_high = pos["extension_high"]
            if extension_high is None:
                entry_level = pos.get("entry_level", pos["entry_price"])
                extension_high = (
                    (bar["High"] - entry_level) / max(entry_level, EPSILON)
                ) >= extension_thresh
            r1_trim_allowed = extension_high and (rejection_bar or momentum_weakening)

            # Proxy invalidations: structure-break close vs stop buffer and optional AVWAP reclaim fail.
            invalidation_triggered = False
            invalidation_threshold = (
                pos["stop"] * (1 + invalidation_stop_buffer_pct)
                if sign > 0
                else pos["stop"] * (1 - invalidation_stop_buffer_pct)
            )
            if sign > 0 and bar["Close"] < invalidation_threshold:
                invalidation_triggered = True
            if sign < 0 and bar["Close"] > invalidation_threshold:
                invalidation_triggered = True
            if (
                not invalidation_triggered
                and pos["avwap_reclaim_failed"]
                and pos["hold_days"] >= 1
                and bar["Close"] < pos.get("entry_level", pos["entry_price"])
            ):
                invalidation_triggered = True

            if stop_hit:
                exit_price = _apply_slippage(
                    pos["stop"], bps=slippage_bps, direction=pos["direction"], is_entry=False
                )
                qty = pos["remaining_qty"]
                equity_before = cash + _compute_positions_value(history, positions, session_date)
                pnl = sign * (exit_price - pos["entry_price"]) * qty
                cash += sign * exit_price * qty
                pos["remaining_qty"] = 0.0
                pos["realized_pnl"] += pnl
                equity_after = cash + _compute_positions_value(history, positions, session_date)
                mae = sign * (pos["mae_price"] - pos["entry_price"]) * pos["initial_qty"]
                mfe = sign * (pos["mfe_price"] - pos["entry_price"]) * pos["initial_qty"]
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": pos["direction"],
                        "fill_type": "exit",
                        "reason": "stop",
                        "entry_reason": None,
                        "exit_reason": "stop",
                        "price": exit_price,
                        "qty": qty,
                        "remaining_qty": 0.0,
                        "pnl": pnl,
                        "notional": exit_price * qty,
                        "slippage_bps": slippage_bps,
                        "ideal_fill_price": pos["stop"],
                        "slippage_actual_bps": slippage_bps,
                        "equity_before": equity_before,
                        "equity_after": equity_after,
                        "position_id": pos["position_id"],
                        "hold_days": pos["hold_days"],
                        "mae": mae,
                        "mfe": mfe,
                    }
                )
                trades_fills_today += 1
                stops_today += 1
                closed_positions.append(
                    {
                        "position_id": pos["position_id"],
                        "entry_date": pos["entry_date"],
                        "exit_date": session_date,
                        "pnl": pos["realized_pnl"],
                        "hold_days": pos["hold_days"],
                        "mae": mae,
                        "mfe": mfe,
                    }
                )
                del positions[symbol]
                continue

            if r1_hit and not pos["r1_trimmed"] and r1_trim_allowed:
                trim_qty = pos["initial_qty"] * TRIM_PCT
                trim_qty = min(trim_qty, pos["remaining_qty"])
                if trim_qty > 0:
                    trim_price = _apply_slippage(
                        pos["r1"], bps=slippage_bps, direction=pos["direction"], is_entry=False
                    )
                    equity_before = cash + _compute_positions_value(history, positions, session_date)
                    pnl = sign * (trim_price - pos["entry_price"]) * trim_qty
                    cash += sign * trim_price * trim_qty
                    pos["remaining_qty"] -= trim_qty
                    pos["r1_trimmed"] = True
                    pos["realized_pnl"] += pnl
                    equity_after = cash + _compute_positions_value(history, positions, session_date)
                    trades.append(
                        {
                            "date": session_date.date().isoformat(),
                            "symbol": symbol,
                            "direction": pos["direction"],
                            "fill_type": "trim",
                            "reason": "target_r1",
                            "entry_reason": None,
                            "exit_reason": "target_r1",
                            "price": trim_price,
                            "qty": trim_qty,
                            "remaining_qty": pos["remaining_qty"],
                            "pnl": pnl,
                            "notional": trim_price * trim_qty,
                            "slippage_bps": slippage_bps,
                            "ideal_fill_price": pos["r1"],
                            "slippage_actual_bps": slippage_bps,
                            "equity_before": equity_before,
                            "equity_after": equity_after,
                            "position_id": pos["position_id"],
                            "hold_days": pos["hold_days"],
                            "mae": None,
                            "mfe": None,
                        }
                    )
                    trades_fills_today += 1
                    targets_r1_today += 1

            if r2_hit and pos["remaining_qty"] > 0:
                exit_price = _apply_slippage(
                    pos["r2"], bps=slippage_bps, direction=pos["direction"], is_entry=False
                )
                qty = pos["remaining_qty"]
                equity_before = cash + _compute_positions_value(history, positions, session_date)
                pnl = sign * (exit_price - pos["entry_price"]) * qty
                cash += sign * exit_price * qty
                pos["remaining_qty"] = 0.0
                pos["realized_pnl"] += pnl
                equity_after = cash + _compute_positions_value(history, positions, session_date)
                mae = sign * (pos["mae_price"] - pos["entry_price"]) * pos["initial_qty"]
                mfe = sign * (pos["mfe_price"] - pos["entry_price"]) * pos["initial_qty"]
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": pos["direction"],
                        "fill_type": "exit",
                        "reason": "target_r2",
                        "entry_reason": None,
                        "exit_reason": "target_r2",
                        "price": exit_price,
                        "qty": qty,
                        "remaining_qty": 0.0,
                        "pnl": pnl,
                        "notional": exit_price * qty,
                        "slippage_bps": slippage_bps,
                        "ideal_fill_price": pos["r2"],
                        "slippage_actual_bps": slippage_bps,
                        "equity_before": equity_before,
                        "equity_after": equity_after,
                        "position_id": pos["position_id"],
                        "hold_days": pos["hold_days"],
                        "mae": mae,
                        "mfe": mfe,
                    }
                )
                trades_fills_today += 1
                targets_r2_today += 1
                closed_positions.append(
                    {
                        "position_id": pos["position_id"],
                        "entry_date": pos["entry_date"],
                        "exit_date": session_date,
                        "pnl": pos["realized_pnl"],
                        "hold_days": pos["hold_days"],
                        "mae": mae,
                        "mfe": mfe,
                    }
                )
                del positions[symbol]
                continue

            if invalidation_triggered and pos["remaining_qty"] > 0:
                exit_price = _apply_slippage(
                    bar["Close"], bps=slippage_bps, direction=pos["direction"], is_entry=False
                )
                qty = pos["remaining_qty"]
                equity_before = cash + _compute_positions_value(history, positions, session_date)
                pnl = sign * (exit_price - pos["entry_price"]) * qty
                cash += sign * exit_price * qty
                pos["remaining_qty"] = 0.0
                pos["realized_pnl"] += pnl
                equity_after = cash + _compute_positions_value(history, positions, session_date)
                mae = sign * (pos["mae_price"] - pos["entry_price"]) * pos["initial_qty"]
                mfe = sign * (pos["mfe_price"] - pos["entry_price"]) * pos["initial_qty"]
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": pos["direction"],
                        "fill_type": "exit",
                        "reason": "invalidation",
                        "entry_reason": None,
                        "exit_reason": "invalidation",
                        "price": exit_price,
                        "qty": qty,
                        "remaining_qty": 0.0,
                        "pnl": pnl,
                        "notional": exit_price * qty,
                        "slippage_bps": slippage_bps,
                        "ideal_fill_price": bar["Close"],
                        "slippage_actual_bps": slippage_bps,
                        "equity_before": equity_before,
                        "equity_after": equity_after,
                        "position_id": pos["position_id"],
                        "hold_days": pos["hold_days"],
                        "mae": mae,
                        "mfe": mfe,
                    }
                )
                trades_fills_today += 1
                invalidations_today += 1
                closed_positions.append(
                    {
                        "position_id": pos["position_id"],
                        "entry_date": pos["entry_date"],
                        "exit_date": session_date,
                        "pnl": pos["realized_pnl"],
                        "hold_days": pos["hold_days"],
                        "mae": mae,
                        "mfe": mfe,
                    }
                )
                del positions[symbol]
                continue

            if pos["hold_days"] >= max_hold_days and pos["remaining_qty"] > 0:
                exit_price = _apply_slippage(
                    bar["Close"], bps=slippage_bps, direction=pos["direction"], is_entry=False
                )
                qty = pos["remaining_qty"]
                equity_before = cash + _compute_positions_value(history, positions, session_date)
                pnl = sign * (exit_price - pos["entry_price"]) * qty
                cash += sign * exit_price * qty
                pos["remaining_qty"] = 0.0
                pos["realized_pnl"] += pnl
                equity_after = cash + _compute_positions_value(history, positions, session_date)
                mae = sign * (pos["mae_price"] - pos["entry_price"]) * pos["initial_qty"]
                mfe = sign * (pos["mfe_price"] - pos["entry_price"]) * pos["initial_qty"]
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": pos["direction"],
                        "fill_type": "exit",
                        "reason": "time_stop",
                        "entry_reason": None,
                        "exit_reason": "time_stop",
                        "price": exit_price,
                        "qty": qty,
                        "remaining_qty": 0.0,
                        "pnl": pnl,
                        "notional": exit_price * qty,
                        "slippage_bps": slippage_bps,
                        "ideal_fill_price": bar["Close"],
                        "slippage_actual_bps": slippage_bps,
                        "equity_before": equity_before,
                        "equity_after": equity_after,
                        "position_id": pos["position_id"],
                        "hold_days": pos["hold_days"],
                        "mae": mae,
                        "mfe": mfe,
                    }
                )
                trades_fills_today += 1
                closed_positions.append(
                    {
                        "position_id": pos["position_id"],
                        "entry_date": pos["entry_date"],
                        "exit_date": session_date,
                        "pnl": pos["realized_pnl"],
                        "hold_days": pos["hold_days"],
                        "mae": mae,
                        "mfe": mfe,
                    }
                )
                del positions[symbol]

            if symbol in positions:
                pos["prior_close"] = bar["Close"]

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

            # Phase 7: Point-in-time earnings exclusion
            if earnings_calendar_df is not None:
                from universe.point_in_time_earnings import is_near_earnings_pit
                if is_near_earnings_pit(
                    symbol,
                    session_date.date().isoformat(),
                    earnings_calendar_df,
                ):
                    continue

            direction = str(row.get("Direction", "Long"))
            entry_level = float(row.get("Entry_Level", row.get("Price", row["Stop_Loss"])))
            extension_high = _extension_high_from_candidate(row)
            avwap_reclaim = str(row.get("Setup_AVWAP_Reclaim", "")).lower()
            avwap_accept = str(row.get("Setup_AVWAP_Acceptance", "")).lower()
            avwap_reclaim_failed = any(token in avwap_reclaim for token in ("fail", "reject")) or any(
                token in avwap_accept for token in ("fail", "reject")
            )
            entry_reason = "signal"

            if entry_model == ENTRY_MODEL_SAME_CLOSE:
                bar = get_bar(history, symbol, session_date)
                if bar is None:
                    continue
                ideal_price = bar["Close"]
                entry_price = _apply_slippage(
                    ideal_price, bps=slippage_bps, direction=direction, is_entry=True
                )
                if not _marketable_limit_ok(
                    ideal=ideal_price,
                    slipped=entry_price,
                    direction=direction,
                    entry_limit_bps=entry_limit_bps,
                ):
                    entries_missed_limit += 1
                    continue
                # Phase 5: Sector cap check
                gross_exposure = _compute_gross_exposure(history, positions, session_date)
                sector_allowed_sc, sector_reason_sc = _check_backtest_sector_cap(
                    candidate_symbol=symbol,
                    positions=positions,
                    sector_map=sector_map,
                    cfg=cfg,
                    gross_exposure=gross_exposure,
                )
                if not sector_allowed_sc:
                    continue

                # Phase 5: Correlation penalty
                corr_penalty_val_sc = _compute_correlation_penalty(
                    candidate_symbol=symbol,
                    positions=positions,
                    history=history,
                    session_date=session_date,
                    cfg=cfg,
                )

                equity_before = cash + _compute_positions_value(history, positions, session_date)
                risk_per_share = _risk_per_share(entry_price, float(row["Stop_Loss"]), direction)
                dollar_risk = equity_before * risk_per_trade_pct * (1.0 - corr_penalty_val_sc)
                base_qty = math.floor(dollar_risk / risk_per_share)
                if base_qty < 1:
                    entries_skipped_size_zero += 1
                    continue
                base_notional = entry_price * base_qty
                if base_notional < min_dollar_position:
                    entries_skipped_size_zero += 1
                    continue
                if _direction_sign(direction) > 0 and base_notional > cash + EPSILON:
                    entries_skipped_cash += 1
                    continue
                base_trade_risk = risk_per_share * base_qty
                risk_controls_result = _resolve_risk_controls(session_date.date().isoformat())
                effective_max_positions = None
                effective_max_gross_exposure_abs = None
                if risk_controls_result is not None:
                    rc = risk_controls_result.controls
                    if rc.max_positions is not None:
                        effective_max_positions = int(rc.max_positions)
                    if rc.max_gross_exposure is not None:
                        effective_max_gross_exposure_abs = float(rc.max_gross_exposure)

                _enforce_entry_guardrails(
                    scan_cfg=cfg,
                    session_date=session_date,
                    symbol=symbol,
                    entries_filled_today=entries_filled_today,
                    unique_symbols_today=symbols_traded_today,
                    positions=positions,
                    equity_before=equity_before,
                    gross_exposure=gross_exposure,
                    notional=base_notional,
                    trade_risk=base_trade_risk,
                    effective_max_positions=effective_max_positions,
                    effective_max_gross_exposure_abs=effective_max_gross_exposure_abs,
                    effective_max_gross_exposure_pct=_compute_dynamic_exposure_pct(),
                )
                qty = base_qty
                if risk_controls_result is not None:
                    min_qty = None
                    if min_dollar_position > 0:
                        min_qty = int(math.ceil(min_dollar_position / entry_price))
                    qty = adjust_order_quantity(
                        base_qty=base_qty,
                        price=entry_price,
                        account_equity=equity_before,
                        risk_controls=risk_controls_result.controls,
                        gross_exposure=gross_exposure,
                        min_qty=min_qty,
                    )
                    if risk_attribution.attribution_write_enabled():
                        try:
                            throttle = risk_controls_result.throttle or {}
                            throttle_regime_label = throttle.get("regime_label")
                            throttle_policy_ref = risk_attribution.resolve_throttle_policy_reference(
                                repo_root=repo_root,
                                ny_date=session_date.date().isoformat(),
                                source=risk_controls_result.source,
                            )
                            event = risk_attribution.build_attribution_event(
                                date_ny=session_date.date().isoformat(),
                                symbol=symbol,
                                baseline_qty=base_qty,
                                modulated_qty=qty,
                                price=entry_price,
                                account_equity=equity_before,
                                gross_exposure=gross_exposure,
                                risk_controls=risk_controls_result.controls,
                                risk_control_reasons=risk_controls_result.reasons,
                                throttle_source=risk_controls_result.source,
                                throttle_regime_label=throttle_regime_label,
                                throttle_policy_ref=throttle_policy_ref,
                                drawdown=drawdown_value,
                                drawdown_threshold=drawdown_threshold,
                                min_qty=min_qty,
                                source="backtest_engine",
                                correlation_penalty=corr_penalty_val_sc,
                            )
                            risk_attribution.write_attribution_event(event)
                        except Exception as exc:
                            print(f"WARN: risk attribution write failed for {symbol}: {exc}")
                notional = entry_price * qty
                trade_risk = risk_per_share * qty
                sign = _direction_sign(direction)
                cash -= sign * entry_price * qty
                sym_hist = get_symbol_history(history, symbol, session_date)
                prior_close = None
                if len(sym_hist) >= 2:
                    prior_close = float(sym_hist.iloc[-2]["Close"])
                position = {
                    "position_id": next_position_id,
                    "symbol": symbol,
                    "direction": direction,
                    "entry_date": session_date,
                    "entry_price": entry_price,
                    "qty": float(qty),
                    "initial_qty": float(qty),
                    "remaining_qty": float(qty),
                    "stop": float(row["Stop_Loss"]),
                    "r1": float(row["Target_R1"]),
                    "r2": float(row["Target_R2"]),
                    "hold_days": 0,
                    "r1_trimmed": False,
                    "entry_level": entry_level,
                    "extension_high": extension_high,
                    "avwap_reclaim_failed": avwap_reclaim_failed,
                    "realized_pnl": 0.0,
                    "mae_price": entry_price,
                    "mfe_price": entry_price,
                    "prior_close": prior_close,
                }
                positions[symbol] = position
                equity_after = cash + _compute_positions_value(history, positions, session_date)
                trades.append(
                    {
                        "date": session_date.date().isoformat(),
                        "symbol": symbol,
                        "direction": direction,
                        "fill_type": "entry",
                        "reason": "signal",
                        "entry_reason": entry_reason,
                        "exit_reason": None,
                        "price": entry_price,
                        "qty": qty,
                        "remaining_qty": qty,
                        "pnl": 0.0,
                        "notional": notional,
                        "slippage_bps": slippage_bps,
                        "ideal_fill_price": ideal_price,
                        "slippage_actual_bps": slippage_bps,
                        "equity_before": equity_before,
                        "equity_after": equity_after,
                        "position_id": next_position_id,
                        "hold_days": 0,
                        "mae": None,
                        "mfe": None,
                    }
                )
                entries_placed_today += 1
                entries_filled_today += 1
                trades_fills_today += 1
                symbols_traded_today.add(symbol)
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
                        "entry_level": entry_level,
                        "extension_high": extension_high,
                        "avwap_reclaim_failed": avwap_reclaim_failed,
                        "entry_reason": entry_reason,
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
                "entries_skipped_max_positions": entries_skipped_max_positions,
                "entries_skipped_cash": entries_skipped_cash,
                "entries_skipped_gross_exposure": entries_skipped_gross_exposure,
                "entries_skipped_size_zero": entries_skipped_size_zero,
                "entries_missed_limit": entries_missed_limit,
                "invalidations_today": invalidations_today,
                "stops_today": stops_today,
                "targets_r1_today": targets_r1_today,
                "targets_r2_today": targets_r2_today,
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
        "entry_reason",
        "exit_reason",
        "price",
        "qty",
        "remaining_qty",
        "pnl",
        "notional",
        "slippage_bps",
        "ideal_fill_price",
        "slippage_actual_bps",
        "equity_before",
        "equity_after",
        "position_id",
        "hold_days",
        "mae",
        "mfe",
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

    trades_df = _round_frame(
        trades_df,
        [
            "price",
            "qty",
            "remaining_qty",
            "pnl",
            "notional",
            "slippage_bps",
            "ideal_fill_price",
            "slippage_actual_bps",
            "equity_before",
            "equity_after",
            "mae",
            "mfe",
        ],
        decimals=4,
    )
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
    win_pnls = [pos["pnl"] for pos in closed_positions if pos["pnl"] > 0]
    loss_pnls = [pos["pnl"] for pos in closed_positions if pos["pnl"] < 0]
    gross_profit = sum(win_pnls)
    gross_loss = abs(sum(loss_pnls))
    profit_factor = (gross_profit / gross_loss) if gross_loss else 0.0
    avg_win = (sum(win_pnls) / len(win_pnls)) if win_pnls else 0.0
    avg_loss = (abs(sum(loss_pnls)) / len(loss_pnls)) if loss_pnls else 0.0
    expectancy = (
        sum(pos["pnl"] for pos in closed_positions) / len(closed_positions)
        if closed_positions
        else 0.0
    )

    max_drawdown = 0.0
    if not equity_df.empty:
        running_max = equity_df["equity"].cummax()
        drawdowns = (equity_df["equity"] - running_max) / running_max
        max_drawdown = float(drawdowns.min())

    final_equity = float(equity_df["equity"].iloc[-1]) if not equity_df.empty else initial_cash
    total_return = (final_equity - initial_cash) / initial_cash if initial_cash else 0.0
    exposure_avg_pct = 0.0
    max_concurrent_positions = 0
    if not equity_df.empty:
        exposure_series = equity_df["positions_value"] / equity_df["equity"].replace(0, pd.NA)
        exposure_avg_pct = float(exposure_series.fillna(0).mean())
        max_concurrent_positions = int(equity_df["open_positions"].max())
    avg_position_size = (
        float(trades_df.loc[trades_df["fill_type"] == "entry", "notional"].mean())
        if not trades_df.empty and "notional" in trades_df.columns
        else 0.0
    )

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
        "profit_factor": round(profit_factor, 6),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "expectancy": round(expectancy, 4),
        "exposure_avg_pct": round(exposure_avg_pct, 6),
        "avg_position_size": round(avg_position_size, 4),
        "max_concurrent_positions": max_concurrent_positions,
    }

    summary.update(
        {
            "run_id": run_id,
            "git_sha": git_sha_value,
            "config_hash": config_hash,
            "data_hash": data_hash,
            "data_path": str(data_path),
            "execution_mode": execution_mode,
            "parameters_used": parameters_used,
            "constituency_source": constituency_source,
            "corporate_actions_hash": corporate_actions_hash_value,
        }
    )
    require_provenance_fields(summary, context="summary.json")

    run_meta = {
        "run_id": run_id,
        "git_sha": git_sha_value,
        "config_hash": config_hash,
        "data_hash": data_hash,
        "data_path": str(data_path),
        "execution_mode": execution_mode,
        "parameters_used": parameters_used,
        "constituency_source": constituency_source,
        "corporate_actions_hash": corporate_actions_hash_value,
        "command": " ".join(sys.argv),
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
        },
    }
    require_provenance_fields(run_meta, context="run_meta.json")

    trades_path = output_dir / "trades.csv"
    positions_path = output_dir / "positions.csv"
    equity_curve_path = output_dir / "equity_curve.csv"
    summary_path = output_dir / "summary.json"
    diagnostics_path = output_dir / "scan_diagnostics.csv"

    _atomic_write_csv(trades_df, trades_path)
    _atomic_write_csv(positions_df, positions_path)
    _atomic_write_csv(equity_df, equity_curve_path)
    _atomic_write_json(summary, summary_path)
    if risk_attribution_summary.summary_write_enabled():
        for session_date in trading_days:
            ny_date = pd.Timestamp(session_date).date().isoformat()
            input_path = risk_attribution_summary.resolve_input_path(ny_date=ny_date)
            if input_path.exists():
                risk_attribution_summary.generate_and_write_daily_summary(
                    ny_date=ny_date,
                    source="backtest_engine",
                )
    end_date_ny = None
    if trading_days:
        end_date_ny = pd.Timestamp(trading_days[-1]).date().isoformat()
    if risk_attribution_rolling.rolling_write_enabled():
        try:
            if end_date_ny:
                risk_attribution_rolling.generate_and_write_rolling_summary(
                    as_of_date_ny=end_date_ny,
                )
        except Exception as exc:
            print(f"WARN: risk attribution rolling write failed: {exc}")
    if end_date_ny:
        try:
            risk_attribution_slack_summary.maybe_send_slack_summary(as_of=end_date_ny)
        except Exception as exc:
            print(f"WARN: risk attribution slack summary failed: {exc}")
    if write_run_meta:
        _atomic_write_json(run_meta, output_dir / "run_meta.json")
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
        "entries_skipped_max_positions",
        "entries_skipped_cash",
        "entries_skipped_gross_exposure",
        "entries_skipped_size_zero",
        "entries_missed_limit",
        "invalidations_today",
        "stops_today",
        "targets_r1_today",
        "targets_r2_today",
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

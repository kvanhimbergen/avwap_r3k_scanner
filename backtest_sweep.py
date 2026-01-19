from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import pandas as pd
import yaml

from backtest_engine import (
    DEFAULT_OHLCV_PATH,
    DEFAULT_OUTPUT_DIR,
    ENTRY_MODEL_NEXT_OPEN,
    load_ohlcv_history,
    run_backtest,
)


ALLOWED_SWEEP_PARAMS = {
    "slippage_bps",
    "entry_limit_bps",
    "risk_per_trade_pct",
    "max_positions",
    "max_gross_exposure_pct",
    "stop_buffer",
    "extension_thresh",
    "invalidation_stop_buffer_pct",
}

ALLOWED_BASE_PARAMS = {
    "start_date",
    "end_date",
    "entry_model",
}.union(ALLOWED_SWEEP_PARAMS)

SUMMARY_COLUMNS = [
    "run_id",
    "data_label",
    "data_path",
    "data_hash",
    "start_date",
    "end_date",
    "entry_model",
    "slippage_bps",
    "entry_limit_bps",
    "risk_per_trade_pct",
    "max_positions",
    "max_gross_exposure_pct",
    "stop_buffer",
    "extension_thresh",
    "invalidation_stop_buffer_pct",
    "walk_forward_label",
    "is_start",
    "is_end",
    "oos_start",
    "oos_end",
    "initial_equity",
    "final_equity",
    "total_return",
    "total_trades",
    "win_rate",
    "max_drawdown",
    "avg_hold_days",
    "profit_factor",
    "avg_win",
    "avg_loss",
    "expectancy",
    "exposure_avg_pct",
    "avg_position_size",
    "max_concurrent_positions",
]


def _ensure_local_path(path: Path) -> None:
    parsed = urlparse(str(path))
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"Only local filesystem paths are allowed: {path}")


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compute_data_hash(path: Path) -> str:
    _ensure_local_path(path)
    with open(path, "rb") as handle:
        return _sha256_bytes(handle.read())


def compute_config_hash(cfg) -> str:
    keys = [
        "BACKTEST_ENTRY_MODEL",
        "BACKTEST_MAX_HOLD_DAYS",
        "BACKTEST_INITIAL_CASH",
        "BACKTEST_INITIAL_EQUITY",
        "BACKTEST_MIN_DOLLAR_POSITION",
        "BACKTEST_STRICT_SCHEMA",
        "BACKTEST_DEBUG_SAVE_CANDIDATES",
        "BACKTEST_VERBOSE",
        "BACKTEST_DYNAMIC_SCAN",
        "BACKTEST_STATIC_UNIVERSE",
        "BACKTEST_USE_DATED_UNIVERSE_SNAPSHOTS",
    ]
    subset = {key: getattr(cfg, key, None) for key in keys}
    return _sha256_bytes(_canonical_json(subset).encode("utf-8"))


def compute_run_id(
    git_sha: str, config_hash: str, params: dict, data_hash: str
) -> str:
    payload = {
        "git_sha": git_sha,
        "config_hash": config_hash,
        "params": params,
        "data_hash": data_hash,
    }
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def load_sweep_spec(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Sweep spec not found: {path}")
    if path.suffix.lower() in {".yaml", ".yml"}:
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def expand_grid(grid: dict) -> list[dict]:
    if not grid:
        return [{}]
    keys = sorted(grid.keys())
    values = []
    for key in keys:
        vals = grid[key]
        if not isinstance(vals, (list, tuple)):
            raise ValueError(f"Grid values must be lists for '{key}'")
        values.append(list(vals))
    combos = [{}]
    for key, vals in zip(keys, values, strict=False):
        next_combos = []
        for combo in combos:
            for val in vals:
                updated = dict(combo)
                updated[key] = val
                next_combos.append(updated)
        combos = next_combos
    return combos


def parse_walk_forward_spec(value: str | None) -> dict | None:
    if not value:
        return None
    path = Path(value)
    if path.exists():
        return load_sweep_spec(path)
    return json.loads(value)


def _normalize_date(value: str | pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _trading_days_from_history(history: pd.DataFrame) -> list[pd.Timestamp]:
    dates = history.index.get_level_values("Date")
    return (
        pd.Series(dates)
        .dropna()
        .dt.normalize()
        .drop_duplicates()
        .sort_values()
        .tolist()
    )


def compute_walk_forward_splits(
    trading_days: list[pd.Timestamp], spec: dict | None
) -> list[dict]:
    if not spec:
        if not trading_days:
            return []
        return [
            {
                "label": "full",
                "is_start": trading_days[0],
                "is_end": trading_days[-1],
                "oos_start": None,
                "oos_end": None,
            }
        ]

    mode = str(spec.get("mode", "single")).lower()
    if mode == "single":
        start = spec.get("is_start") or spec.get("start") or trading_days[0]
        is_end = spec.get("is_end")
        oos_start = spec.get("oos_start")
        oos_end = spec.get("oos_end") or spec.get("end") or trading_days[-1]
        if not is_end:
            raise ValueError("walk-forward single mode requires is_end")
        start = _normalize_date(start)
        is_end = _normalize_date(is_end)
        oos_end = _normalize_date(oos_end)
        if oos_start:
            oos_start = _normalize_date(oos_start)
        else:
            future_days = [d for d in trading_days if d > is_end]
            if not future_days:
                raise ValueError("No OOS window available after is_end")
            oos_start = future_days[0]
        return [
            {
                "label": "single",
                "is_start": start,
                "is_end": is_end,
                "oos_start": oos_start,
                "oos_end": oos_end,
            }
        ]

    if mode == "rolling":
        start = _normalize_date(spec.get("start") or trading_days[0])
        end = _normalize_date(spec.get("end") or trading_days[-1])
        is_length = int(spec.get("is_length", 0))
        oos_length = int(spec.get("oos_length", 0))
        step = int(spec.get("step", oos_length))
        if is_length <= 0 or oos_length <= 0 or step <= 0:
            raise ValueError("rolling mode requires positive is_length, oos_length, and step")

        window_days = [d for d in trading_days if start <= d <= end]
        splits = []
        idx = 0
        label_counter = 1
        while idx + is_length + oos_length <= len(window_days):
            is_start = window_days[idx]
            is_end = window_days[idx + is_length - 1]
            oos_start = window_days[idx + is_length]
            oos_end = window_days[idx + is_length + oos_length - 1]
            splits.append(
                {
                    "label": f"rolling_{label_counter}",
                    "is_start": is_start,
                    "is_end": is_end,
                    "oos_start": oos_start,
                    "oos_end": oos_end,
                }
            )
            idx += step
            label_counter += 1
        return splits

    raise ValueError(f"Unsupported walk-forward mode: {mode}")


def compute_regime_labels(
    history: pd.DataFrame, trading_days: list[pd.Timestamp]
) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=["date", "trend_regime", "vol_regime"])
    try:
        spy = history.loc[("SPY", slice(None)), :].reset_index()
    except KeyError:
        return pd.DataFrame(columns=["date", "trend_regime", "vol_regime"])

    spy = spy.sort_values("Date").reset_index(drop=True)
    spy["Date"] = pd.to_datetime(spy["Date"]).dt.normalize()
    spy = spy[spy["Date"].isin(trading_days)].copy()
    if spy.empty:
        return pd.DataFrame(columns=["date", "trend_regime", "vol_regime"])

    close = spy["Close"].astype(float)
    sma_200 = close.rolling(200, min_periods=200).mean()
    sma_slope = sma_200.diff()
    trend = []
    for idx, (c, sma, slope) in enumerate(zip(close, sma_200, sma_slope, strict=False)):
        if pd.isna(sma) or pd.isna(slope):
            trend.append("unknown")
            continue
        if c >= sma and slope >= 0:
            trend.append("up")
        elif c < sma and slope < 0:
            trend.append("down")
        else:
            trend.append("sideways")

    high_low = spy["High"].astype(float)
    low = spy["Low"].astype(float)
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            (high_low - low),
            (high_low - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(14, min_periods=14).mean()
    atr_pct = atr / close.replace(0, pd.NA)
    rolling_median = atr_pct.rolling(60, min_periods=20).median()
    vol_regime = []
    for atr_val, median_val in zip(atr_pct, rolling_median, strict=False):
        if pd.isna(atr_val) or pd.isna(median_val):
            vol_regime.append("unknown")
        elif atr_val >= median_val:
            vol_regime.append("high")
        else:
            vol_regime.append("low")

    return pd.DataFrame(
        {
            "date": spy["Date"].dt.date.astype(str),
            "trend_regime": trend,
            "vol_regime": vol_regime,
        }
    )


def _atomic_write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, path)


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def _data_label_from_path(path: Path) -> str:
    return path.stem


def _normalize_params(base: dict, overrides: dict) -> dict:
    params = dict(base)
    params.update(overrides)
    return params


def _validate_param_keys(params: dict, allowed: set[str]) -> None:
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(f"Unsupported parameters in sweep: {unknown}")


def _prepare_cfg(cfg, params: dict, ohlcv_path: Path, output_dir: Path) -> object:
    cfg_copy = copy.deepcopy(cfg)
    cfg_copy.BACKTEST_OHLCV_PATH = str(ohlcv_path)
    cfg_copy.BACKTEST_OUTPUT_DIR = str(output_dir)
    if "entry_model" in params:
        cfg_copy.BACKTEST_ENTRY_MODEL = params["entry_model"]
    if "slippage_bps" in params:
        cfg_copy.BACKTEST_SLIPPAGE_BPS = float(params["slippage_bps"])
    if "entry_limit_bps" in params:
        cfg_copy.BACKTEST_ENTRY_LIMIT_BPS = float(params["entry_limit_bps"])
    if "risk_per_trade_pct" in params:
        cfg_copy.BACKTEST_RISK_PER_TRADE_PCT = float(params["risk_per_trade_pct"])
    if "max_positions" in params:
        cfg_copy.BACKTEST_MAX_POSITIONS = int(params["max_positions"])
    if "max_gross_exposure_pct" in params:
        cfg_copy.BACKTEST_MAX_GROSS_EXPOSURE_PCT = float(params["max_gross_exposure_pct"])
    stop_buffer = params.get("stop_buffer", params.get("invalidation_stop_buffer_pct"))
    if stop_buffer is not None:
        cfg_copy.BACKTEST_INVALIDATION_STOP_BUFFER_PCT = float(stop_buffer)
    if "extension_thresh" in params:
        cfg_copy.BACKTEST_EXTENSION_THRESH = float(params["extension_thresh"])
    return cfg_copy


def build_summary_row(
    *,
    run_id: str,
    data_label: str,
    data_path: Path,
    data_hash: str,
    params: dict,
    split: dict,
    summary: dict,
) -> dict:
    def _fmt_date(value):
        if value is None:
            return None
        return str(pd.Timestamp(value).date())

    row = {
        "run_id": run_id,
        "data_label": data_label,
        "data_path": str(data_path),
        "data_hash": data_hash,
        "start_date": summary.get("start_date"),
        "end_date": summary.get("end_date"),
        "entry_model": params.get("entry_model", ENTRY_MODEL_NEXT_OPEN),
        "slippage_bps": params.get("slippage_bps"),
        "entry_limit_bps": params.get("entry_limit_bps"),
        "risk_per_trade_pct": params.get("risk_per_trade_pct"),
        "max_positions": params.get("max_positions"),
        "max_gross_exposure_pct": params.get("max_gross_exposure_pct"),
        "stop_buffer": params.get("stop_buffer"),
        "extension_thresh": params.get("extension_thresh"),
        "invalidation_stop_buffer_pct": params.get("invalidation_stop_buffer_pct"),
        "walk_forward_label": split.get("label"),
        "is_start": _fmt_date(split.get("is_start")),
        "is_end": _fmt_date(split.get("is_end")),
        "oos_start": _fmt_date(split.get("oos_start")),
        "oos_end": _fmt_date(split.get("oos_end")),
    }
    row.update(summary)
    return row


def build_summary_table(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df.reindex(columns=SUMMARY_COLUMNS)
    if not df.empty:
        df = df.sort_values(["run_id"]).reset_index(drop=True)
    return df


def build_leaderboard(rows: list[dict]) -> dict:
    metrics = {
        "total_return": "desc",
        "final_equity": "desc",
        "win_rate": "desc",
        "profit_factor": "desc",
        "expectancy": "desc",
        "max_drawdown": "asc",
    }
    leaderboard = {}
    for metric, direction in metrics.items():
        filtered = [row for row in rows if row.get(metric) is not None]
        if direction == "desc":
            filtered.sort(key=lambda r: (-float(r.get(metric, 0)), r["run_id"]))
        else:
            filtered.sort(key=lambda r: (float(r.get(metric, 0)), r["run_id"]))
        leaderboard[metric] = [
            {"run_id": row["run_id"], "value": row.get(metric)}
            for row in filtered[:5]
        ]
    return leaderboard


def write_notes(path: Path) -> None:
    content = """# Backtest Comparison Notes

This directory contains aggregated comparisons across sweep runs.

## summary_table.csv
- One row per run.
- Includes the input parameters, data snapshot metadata, walk-forward split identifiers,
  and key performance metrics from summary.json.

## leaderboard.json
- Ranked lists for common performance metrics.
- max_drawdown is sorted ascending (more negative drawdowns rank lower).

## Reproducibility
- Run IDs are deterministic hashes of git SHA, config hash, run params, and data hash.
- Use params.json and run_meta.json in each run folder to reproduce inputs.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_sweep(
    *,
    cfg,
    start_date: str | None = None,
    end_date: str | None = None,
    entry_model: str | None = None,
    sweep_spec: dict | None = None,
    walk_forward_spec: dict | None = None,
    ohlcv_paths: Iterable[Path] | None = None,
    output_root: Path | None = None,
) -> list[dict]:
    spec = sweep_spec or {}
    base_params = spec.get("base_params", {})
    _validate_param_keys(base_params, ALLOWED_BASE_PARAMS)

    if start_date:
        base_params["start_date"] = start_date
    if end_date:
        base_params["end_date"] = end_date
    if entry_model:
        base_params["entry_model"] = entry_model

    grid = spec.get("grid", {})
    _validate_param_keys(grid, ALLOWED_SWEEP_PARAMS)
    grid_params = expand_grid(grid)

    data_entries = spec.get("data_paths") or spec.get("ohlcv_paths")
    if ohlcv_paths:
        data_entries = list(ohlcv_paths)
    if not data_entries:
        data_entries = [Path(getattr(cfg, "BACKTEST_OHLCV_PATH", DEFAULT_OHLCV_PATH))]

    normalized_entries = []
    for entry in data_entries:
        if isinstance(entry, dict):
            path = Path(entry["path"])
            label = entry.get("label") or _data_label_from_path(path)
        else:
            path = Path(entry)
            label = _data_label_from_path(path)
        normalized_entries.append({"path": path, "label": label})
    normalized_entries.sort(key=lambda item: (str(item["path"]), item["label"]))

    output_root = output_root or Path(getattr(cfg, "BACKTEST_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    runs_dir = output_root / "runs"
    compare_dir = output_root / "compare"

    git_sha = _git_sha()
    config_hash = compute_config_hash(cfg)
    all_rows = []

    for data_entry in normalized_entries:
        data_path = Path(data_entry["path"])
        data_label = data_entry["label"]
        _ensure_local_path(data_path)
        data_hash = compute_data_hash(data_path)

        history = load_ohlcv_history(data_path)
        trading_days = _trading_days_from_history(history)
        wf_spec = walk_forward_spec or spec.get("walk_forward")
        splits = compute_walk_forward_splits(trading_days, wf_spec)

        regime_df = compute_regime_labels(history, trading_days)

        for split in splits:
            run_start = split["is_start"]
            run_end = split["is_end"]
            for overrides in grid_params:
                params = _normalize_params(base_params, overrides)
                if "start_date" in params:
                    run_start = _normalize_date(params["start_date"])
                if "end_date" in params:
                    run_end = _normalize_date(params["end_date"])

                params = dict(params)
                params["start_date"] = str(run_start.date())
                params["end_date"] = str(run_end.date())

                run_id = compute_run_id(git_sha, config_hash, params, data_hash)
                run_dir = runs_dir / run_id

                cfg_run = _prepare_cfg(cfg, params, data_path, run_dir)
                result = run_backtest(cfg_run, run_start, run_end)

                params_path = run_dir / "params.json"
                _atomic_write_json(params, params_path)

                meta = {
                    "run_id": run_id,
                    "git_sha": git_sha,
                    "config_hash": config_hash,
                    "data_hash": data_hash,
                    "data_path": str(data_path),
                    "data_label": data_label,
                    "command": " ".join(sys.argv),
                    "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                    "environment": {
                        "python": sys.version,
                        "platform": platform.platform(),
                    },
                }
                _atomic_write_json(meta, run_dir / "run_meta.json")

                if not regime_df.empty:
                    _atomic_write_csv(regime_df, run_dir / "regime.csv")
                else:
                    _atomic_write_csv(
                        pd.DataFrame(columns=["date", "trend_regime", "vol_regime"]),
                        run_dir / "regime.csv",
                    )

                row = build_summary_row(
                    run_id=run_id,
                    data_label=data_label,
                    data_path=data_path,
                    data_hash=data_hash,
                    params=params,
                    split=split,
                    summary=result.summary,
                )
                all_rows.append(row)

    summary_table = build_summary_table(all_rows)
    _atomic_write_csv(summary_table, compare_dir / "summary_table.csv")
    leaderboard = build_leaderboard(all_rows)
    _atomic_write_json(leaderboard, compare_dir / "leaderboard.json")
    write_notes(compare_dir / "notes.md")

    return all_rows


def normalize_sweep_spec(spec: dict) -> dict:
    if not spec:
        return {}
    normalized = dict(spec)
    grid = normalized.get("grid")
    if grid is None and any(k in spec for k in ALLOWED_SWEEP_PARAMS):
        grid = {k: spec[k] for k in ALLOWED_SWEEP_PARAMS if k in spec}
        normalized["grid"] = grid
    return normalized


def build_params_from_cfg(cfg) -> dict:
    return {
        "entry_model": getattr(cfg, "BACKTEST_ENTRY_MODEL", ENTRY_MODEL_NEXT_OPEN),
        "slippage_bps": getattr(cfg, "BACKTEST_SLIPPAGE_BPS", None),
        "entry_limit_bps": getattr(cfg, "BACKTEST_ENTRY_LIMIT_BPS", None),
        "risk_per_trade_pct": getattr(cfg, "BACKTEST_RISK_PER_TRADE_PCT", None),
        "max_positions": getattr(cfg, "BACKTEST_MAX_POSITIONS", None),
        "max_gross_exposure_pct": getattr(cfg, "BACKTEST_MAX_GROSS_EXPOSURE_PCT", None),
        "stop_buffer": getattr(cfg, "BACKTEST_INVALIDATION_STOP_BUFFER_PCT", None),
        "extension_thresh": getattr(cfg, "BACKTEST_EXTENSION_THRESH", None),
        "invalidation_stop_buffer_pct": getattr(cfg, "BACKTEST_INVALIDATION_STOP_BUFFER_PCT", None),
    }


def serialize_cfg(cfg) -> dict:
    try:
        return asdict(cfg)
    except TypeError:
        return dict(cfg.__dict__)

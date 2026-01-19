from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

import backtest_engine
import scan_engine
from config import cfg
from provenance import (
    compute_config_hash,
    compute_data_hash,
    compute_run_id,
    git_sha,
    require_provenance_fields,
)
from setup_context import load_setup_rules

PARITY_DIR = Path("backtests") / "parity"
PARITY_REPORT_PATH = PARITY_DIR / "parity_report.json"
PARITY_DIFF_PATH = PARITY_DIR / "parity_diff.csv"


@dataclass
class ParityResult:
    is_equal: bool
    report: dict
    diff: pd.DataFrame | None


class ParityMismatchError(AssertionError):
    def __init__(self, report: dict, diff: pd.DataFrame | None) -> None:
        super().__init__("Parity mismatch between scan_engine and backtest_engine outputs.")
        self.report = report
        self.diff = diff


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


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    return sorted(dict.fromkeys([str(sym).upper() for sym in symbols]))


def _direct_scan_candidates(
    history: pd.DataFrame,
    symbols: list[str],
    sector_map: dict[str, str],
    as_of_dt: pd.Timestamp,
    scan_cfg,
) -> pd.DataFrame:
    scan_engine._ACTIVE_CFG = scan_cfg
    setup_rules = load_setup_rules()
    rows: list[dict] = []
    for symbol in symbols:
        sym_hist = backtest_engine.get_symbol_history(history, symbol, as_of_dt)
        if sym_hist.empty:
            continue
        df_slice = sym_hist.set_index("Date").sort_index()
        df_slice = df_slice.loc[:as_of_dt]
        row = scan_engine.build_candidate_row(
            df_slice,
            symbol,
            sector_map.get(symbol, "Unknown"),
            setup_rules,
            as_of_dt=as_of_dt,
            direction="Long",
        )
        if row:
            rows.append(row)
    return scan_engine._build_candidates_dataframe(rows)


def _canonical_columns(columns: list[str]) -> list[str]:
    ordered = [col for col in scan_engine.CANDIDATE_COLUMNS if col in columns]
    extras = [col for col in columns if col not in ordered]
    return ordered + extras


def _normalize_candidates(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    normalized = df.reindex(columns=columns).copy()
    if "Symbol" in normalized.columns:
        normalized["Symbol"] = normalized["Symbol"].astype(str)
        normalized = normalized.sort_values("Symbol", kind="mergesort")
    return normalized.reset_index(drop=True)


def _aligned_frames(
    df_a: pd.DataFrame, df_b: pd.DataFrame, columns: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    max_len = max(len(df_a), len(df_b))
    df_a = df_a.reindex(range(max_len)).reset_index(drop=True)
    df_b = df_b.reindex(range(max_len)).reset_index(drop=True)
    return df_a.reindex(columns=columns), df_b.reindex(columns=columns)


def _compare_frames(
    df_a: pd.DataFrame, df_b: pd.DataFrame, columns: list[str]
) -> tuple[bool, pd.DataFrame | None, dict]:
    mismatches: list[dict] = []
    mismatch_rows: set[int] = set()

    aligned_a, aligned_b = _aligned_frames(df_a, df_b, columns)

    for col in columns:
        series_a = aligned_a[col]
        series_b = aligned_b[col]
        num_a = pd.to_numeric(series_a, errors="coerce")
        num_b = pd.to_numeric(series_b, errors="coerce")
        if num_a.notna().any() or num_b.notna().any():
            matches = (num_a == num_b) | (num_a.isna() & num_b.isna())
        else:
            str_a = series_a.astype(str).fillna("")
            str_b = series_b.astype(str).fillna("")
            matches = str_a == str_b
        if matches.all():
            continue
        mismatch_idx = matches[~matches].index.tolist()
        for idx in mismatch_idx:
            mismatch_rows.add(idx)
            mismatches.append(
                {
                    "row": idx,
                    "symbol": aligned_a.get("Symbol", pd.Series([None])).iloc[idx]
                    if "Symbol" in aligned_a.columns
                    else None,
                    "column": col,
                    "value_a": series_a.iloc[idx],
                    "value_b": series_b.iloc[idx],
                }
            )

    diff_df = pd.DataFrame(mismatches) if mismatches else None
    summary = {
        "mismatch_cells": len(mismatches),
        "mismatch_rows": len(mismatch_rows),
    }
    return len(mismatches) == 0, diff_df, summary


def compare_scan_backtest(
    history: pd.DataFrame,
    symbols: Iterable[str],
    sector_map: dict[str, str],
    as_of_dt: datetime | pd.Timestamp,
    scan_cfg,
    *,
    history_path: Path | None = None,
    raise_on_mismatch: bool = True,
) -> ParityResult:
    symbols_list = _normalize_symbols(symbols)
    as_of_ts = pd.Timestamp(as_of_dt).normalize()

    scan_engine._ACTIVE_CFG = scan_cfg
    direct_df = _direct_scan_candidates(history, symbols_list, sector_map, as_of_ts, scan_cfg)
    backtest_df = backtest_engine._scan_as_of(
        history,
        symbols_list,
        sector_map,
        as_of_ts,
        scan_cfg,
    )

    schema_equal = list(direct_df.columns) == list(backtest_df.columns)
    row_count_equal = len(direct_df) == len(backtest_df)

    all_columns = list(dict.fromkeys(list(direct_df.columns) + list(backtest_df.columns)))
    canonical_columns = _canonical_columns(all_columns)

    direct_norm = _normalize_candidates(direct_df, canonical_columns)
    backtest_norm = _normalize_candidates(backtest_df, canonical_columns)

    frames_equal, diff_df, diff_summary = _compare_frames(
        direct_norm, backtest_norm, canonical_columns
    )

    data_path = str(history_path) if history_path is not None else "unknown"
    data_hash = (
        compute_data_hash(Path(history_path)) if history_path is not None else "unknown"
    )
    parameters_used = {
        "as_of_dt": as_of_ts.date().isoformat(),
        "symbols": symbols_list,
    }
    execution_mode = "single"
    git_sha_value = git_sha()
    config_hash = compute_config_hash(scan_cfg)
    run_id = compute_run_id(
        git_sha_value,
        config_hash,
        data_hash,
        execution_mode,
        parameters_used,
    )

    report = {
        "run_id": run_id,
        "git_sha": git_sha_value,
        "config_hash": config_hash,
        "data_hash": data_hash,
        "data_path": data_path,
        "execution_mode": execution_mode,
        "parameters_used": parameters_used,
        "as_of_dt": as_of_ts.date().isoformat(),
        "symbol_count": len(symbols_list),
        "schema_a": list(direct_df.columns),
        "schema_b": list(backtest_df.columns),
        "row_count_a": int(len(direct_df)),
        "row_count_b": int(len(backtest_df)),
        "mismatch_summary": {
            "schema_equal": schema_equal,
            "row_count_equal": row_count_equal,
            **diff_summary,
        },
    }
    require_provenance_fields(report, context="parity_report.json")

    is_equal = schema_equal and row_count_equal and frames_equal
    _atomic_write_json(report, PARITY_REPORT_PATH)

    if not is_equal:
        if diff_df is not None and not diff_df.empty:
            _atomic_write_csv(diff_df, PARITY_DIFF_PATH)

    result = ParityResult(is_equal=is_equal, report=report, diff=diff_df)

    if not is_equal and raise_on_mismatch:
        raise ParityMismatchError(report, diff_df)

    return result


def _parse_symbols(value: str | None) -> list[str]:
    if not value:
        return []
    return [sym.strip().upper() for sym in value.split(",") if sym.strip()]


def _default_symbols(history: pd.DataFrame, limit: int) -> list[str]:
    tickers = history.index.get_level_values("Ticker").unique().tolist()
    return sorted(tickers)[:limit]


def _default_as_of_date(history: pd.DataFrame) -> pd.Timestamp:
    last_date = history.index.get_level_values("Date").max()
    return pd.Timestamp(last_date).normalize()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run scan/backtest parity checks.")
    parser.add_argument(
        "--history-path",
        help="Path to local OHLCV history parquet file.",
        default=cfg.BACKTEST_OHLCV_PATH,
    )
    parser.add_argument(
        "--symbols",
        help="Comma-separated symbols to include in parity check.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Symbol count to use when --symbols is not provided.",
    )
    parser.add_argument(
        "--as-of",
        help="As-of date (YYYY-MM-DD). Defaults to last date in history.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a small parity check using default config and a few symbols.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.smoke and not args.symbols:
        args.limit = min(args.limit, 3)

    history_path = Path(args.history_path)
    history = backtest_engine.load_ohlcv_history(history_path)

    symbols = _parse_symbols(args.symbols)
    if not symbols:
        symbols = _default_symbols(history, args.limit)

    if not symbols:
        raise ValueError("No symbols available for parity check.")

    as_of_dt = pd.Timestamp(args.as_of) if args.as_of else _default_as_of_date(history)
    sector_map = {symbol: "Unknown" for symbol in symbols}

    result = compare_scan_backtest(
        history,
        symbols,
        sector_map,
        as_of_dt,
        cfg,
        history_path=history_path,
    )

    print(f"Parity run_id: {result.report.get('run_id')}")
    print(f"Parity output directory: {PARITY_DIR}")
    print(f"Parity summary.json: N/A (see {PARITY_REPORT_PATH})")
    print(f"Parity report.json: {PARITY_REPORT_PATH}")
    print("Parity provenance: OK (parity_report.json includes required fields)")


if __name__ == "__main__":
    main()

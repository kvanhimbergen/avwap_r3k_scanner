from __future__ import annotations

from typing import Any

import pandas as pd


def _normalize_columns(history: pd.DataFrame) -> pd.DataFrame:
    cols = {col.lower(): col for col in history.columns}
    date_col = cols.get("date")
    symbol_col = cols.get("ticker") or cols.get("symbol")
    if date_col is None or symbol_col is None:
        raise ValueError("history missing required columns (date, ticker/symbol)")

    df = history[[date_col, symbol_col]].copy()
    df.columns = ["date", "symbol"]
    df["date"] = pd.to_datetime(df["date"], utc=False, errors="coerce").dt.normalize()
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df = df.dropna(subset=["date", "symbol"])
    return df


def resolve_regime_ny_date(history: pd.DataFrame, requested_ny_date: str) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    inputs_snapshot = {"requested_ny_date": requested_ny_date}
    try:
        df = _normalize_columns(history)
    except ValueError:
        return requested_ny_date, reasons, inputs_snapshot

    requested_ts = pd.Timestamp(requested_ny_date).normalize()
    spy = df[df["symbol"] == "SPY"]
    if spy.empty:
        return requested_ny_date, reasons, inputs_snapshot

    spy = spy[spy["date"] <= requested_ts]
    if spy.empty:
        return requested_ny_date, reasons, inputs_snapshot

    last_date = spy["date"].max()
    resolved_ny_date = last_date.date().isoformat()
    inputs_snapshot["resolved_ny_date"] = resolved_ny_date
    if resolved_ny_date != requested_ny_date:
        reasons.append("resolved_to_last_trading_day")
    return resolved_ny_date, reasons, inputs_snapshot

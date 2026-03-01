"""Shared helpers for regime feature computation (E1, E2)."""

from __future__ import annotations

import pandas as pd


def round_value(value: float, places: int = 6) -> float:
    return round(float(value), places)


def normalize_columns(history: pd.DataFrame) -> pd.DataFrame:
    cols = {col.lower(): col for col in history.columns}
    date_col = cols.get("date")
    symbol_col = cols.get("ticker") or cols.get("symbol")
    close_col = cols.get("close")
    if date_col is None or symbol_col is None or close_col is None:
        raise ValueError("history missing required columns (date, ticker, close)")

    df = history[[date_col, symbol_col, close_col]].copy()
    df.columns = ["date", "symbol", "close"]
    df["date"] = pd.to_datetime(df["date"], utc=False, errors="coerce").dt.normalize()
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "symbol", "close"])
    return df


def to_date_string(value: pd.Timestamp) -> str:
    return value.date().isoformat()


def filter_as_of(df: pd.DataFrame, ny_date: str) -> pd.DataFrame:
    cutoff = pd.Timestamp(ny_date).normalize()
    return df[df["date"] <= cutoff]


def symbol_history(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    subset = df[df["symbol"] == symbol].sort_values("date")
    return subset


def series_tail(series: pd.Series, count: int) -> pd.Series:
    if count <= 0:
        return series.iloc[0:0]
    return series.iloc[-count:]

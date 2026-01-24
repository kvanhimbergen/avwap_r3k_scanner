from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

import pandas as pd

VOL_LOOKBACK = 20
DRAWDOWN_LOOKBACK = 63
TREND_SHORT_LOOKBACK = 50
TREND_LONG_LOOKBACK = 200
BREADTH_LOOKBACK = 50
MIN_BREADTH_SYMBOLS = 20


@dataclass(frozen=True)
class RegimeFeatureSet:
    ny_date: str
    last_date: str
    volatility: float
    drawdown: float
    trend: float
    breadth: float
    signals: dict[str, Any]
    inputs_snapshot: dict[str, Any]


@dataclass(frozen=True)
class RegimeFeatureResult:
    ok: bool
    feature_set: RegimeFeatureSet | None
    reason_codes: list[str]
    inputs_snapshot: dict[str, Any]


def _round(value: float, places: int = 6) -> float:
    return round(float(value), places)


def _normalize_columns(history: pd.DataFrame) -> pd.DataFrame:
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


def _to_date_string(value: pd.Timestamp) -> str:
    return value.date().isoformat()


def _filter_as_of(df: pd.DataFrame, ny_date: str) -> pd.DataFrame:
    cutoff = pd.Timestamp(ny_date).normalize()
    return df[df["date"] <= cutoff]


def _symbol_history(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    subset = df[df["symbol"] == symbol].sort_values("date")
    return subset


def _series_tail(series: pd.Series, count: int) -> pd.Series:
    if count <= 0:
        return series.iloc[0:0]
    return series.iloc[-count:]


def _require_length(series: pd.Series, count: int, reason: str, reasons: list[str]) -> bool:
    if len(series) < count:
        reasons.append(reason)
        return False
    return True


def _compute_volatility(closes: pd.Series, reasons: list[str]) -> tuple[float | None, list[float]]:
    returns = closes.pct_change().dropna()
    window = _series_tail(returns, VOL_LOOKBACK)
    if not _require_length(window, VOL_LOOKBACK, "insufficient_vol_history", reasons):
        return None, []
    vol = window.std(ddof=0) * (252 ** 0.5)
    return _round(vol), [_round(val) for val in window.tolist()]


def _compute_drawdown(closes: pd.Series, reasons: list[str]) -> tuple[float | None, list[float]]:
    window = _series_tail(closes, DRAWDOWN_LOOKBACK)
    if not _require_length(window, DRAWDOWN_LOOKBACK, "insufficient_drawdown_history", reasons):
        return None, []
    running_max = window.cummax()
    drawdowns = window / running_max - 1.0
    return _round(drawdowns.min()), [_round(val) for val in window.tolist()]


def _compute_trend(closes: pd.Series, reasons: list[str]) -> tuple[float | None, float | None, float | None]:
    window_long = _series_tail(closes, TREND_LONG_LOOKBACK)
    if not _require_length(window_long, TREND_LONG_LOOKBACK, "insufficient_trend_history", reasons):
        return None, None, None
    window_short = _series_tail(closes, TREND_SHORT_LOOKBACK)
    if not _require_length(window_short, TREND_SHORT_LOOKBACK, "insufficient_trend_short_history", reasons):
        return None, None, None
    ma_short = window_short.mean()
    ma_long = window_long.mean()
    if ma_long == 0:
        reasons.append("invalid_trend_ma")
        return None, None, None
    trend = ma_short / ma_long - 1.0
    return _round(trend), _round(ma_short), _round(ma_long)


def _breadth_fraction(df: pd.DataFrame, ny_date: str) -> tuple[float | None, dict[str, Any], str | None]:
    symbols = sorted(df["symbol"].unique().tolist())
    breadth_symbols: list[str] = []
    above_count = 0
    for symbol in symbols:
        history = _symbol_history(df, symbol)
        history = _filter_as_of(history, ny_date)
        if len(history) < BREADTH_LOOKBACK:
            continue
        closes = history["close"]
        ma = _series_tail(closes, BREADTH_LOOKBACK).mean()
        last_close = closes.iloc[-1]
        breadth_symbols.append(symbol)
        if last_close >= ma:
            above_count += 1
    if len(breadth_symbols) < MIN_BREADTH_SYMBOLS:
        return None, {}, "insufficient_breadth_symbols"
    fraction = above_count / len(breadth_symbols)
    return _round(fraction), {
        "method": "above_ma_fraction",
        "symbols_used": breadth_symbols,
        "above_ma_count": above_count,
    }, None


def _breadth_ratio(df: pd.DataFrame, ny_date: str) -> tuple[float | None, dict[str, Any], str | None]:
    spy = _filter_as_of(_symbol_history(df, "SPY"), ny_date)
    iwm = _filter_as_of(_symbol_history(df, "IWM"), ny_date)
    if spy.empty or iwm.empty:
        return None, {}, "missing_breadth_ratio_symbols"
    merged = pd.merge(spy[["date", "close"]], iwm[["date", "close"]], on="date", suffixes=("_spy", "_iwm"))
    merged = merged.sort_values("date")
    if len(merged) < BREADTH_LOOKBACK:
        return None, {}, "insufficient_breadth_ratio_history"
    ratio = merged["close_iwm"] / merged["close_spy"]
    window = _series_tail(ratio, BREADTH_LOOKBACK)
    ma = window.mean()
    last_ratio = window.iloc[-1]
    if ma == 0:
        return None, {}, "invalid_breadth_ratio"
    breadth_value = 1.0 if last_ratio >= ma else 0.0
    return _round(breadth_value), {
        "method": "iwm_spy_ratio",
        "ratio_window": [_round(val) for val in window.tolist()],
        "ratio_ma": _round(ma),
        "last_ratio": _round(last_ratio),
    }, None


def compute_regime_features(history: pd.DataFrame, ny_date: str) -> RegimeFeatureResult:
    reasons: list[str] = []
    try:
        df = _normalize_columns(history)
    except ValueError:
        reasons.append("invalid_history_columns")
        return RegimeFeatureResult(
            ok=False,
            feature_set=None,
            reason_codes=reasons,
            inputs_snapshot={"ny_date": ny_date, "history_rows": int(len(history))},
        )
    df = _filter_as_of(df, ny_date)

    if df.empty:
        reasons.append("no_history_for_date")
        return RegimeFeatureResult(
            ok=False,
            feature_set=None,
            reason_codes=reasons,
            inputs_snapshot={"ny_date": ny_date, "history_rows": 0},
        )

    spy_history = _symbol_history(df, "SPY")
    if spy_history.empty:
        reasons.append("missing_symbol_spy")
        inputs_snapshot = {
            "ny_date": ny_date,
            "history_rows": int(len(df)),
            "available_symbols": sorted(df["symbol"].unique().tolist()),
        }
        return RegimeFeatureResult(
            ok=False,
            feature_set=None,
            reason_codes=reasons,
            inputs_snapshot=inputs_snapshot,
        )

    spy_closes = spy_history["close"]
    last_date = _to_date_string(spy_history["date"].iloc[-1])
    vol, vol_returns = _compute_volatility(spy_closes, reasons)
    drawdown, drawdown_closes = _compute_drawdown(spy_closes, reasons)
    trend, ma_short, ma_long = _compute_trend(spy_closes, reasons)

    breadth_reasons: list[str] = []
    breadth_value, breadth_snapshot, breadth_reason = _breadth_fraction(df, ny_date)
    if breadth_value is None and breadth_reason:
        breadth_reasons.append(breadth_reason)
    if breadth_value is None:
        breadth_value, breadth_snapshot, breadth_reason = _breadth_ratio(df, ny_date)
        if breadth_value is None and breadth_reason:
            breadth_reasons.append(breadth_reason)
    if breadth_value is None and breadth_reasons:
        reasons.extend(breadth_reasons)

    if reasons:
        inputs_snapshot = {
            "ny_date": ny_date,
            "last_date": last_date,
            "history_rows": int(len(df)),
            "available_symbols": sorted(df["symbol"].unique().tolist()),
        }
        return RegimeFeatureResult(
            ok=False,
            feature_set=None,
            reason_codes=reasons,
            inputs_snapshot=inputs_snapshot,
        )

    spy_close = _round(spy_closes.iloc[-1])

    signals = {
        "volatility": {
            "value": vol,
            "lookback": VOL_LOOKBACK,
        },
        "drawdown": {
            "value": drawdown,
            "lookback": DRAWDOWN_LOOKBACK,
        },
        "trend": {
            "value": trend,
            "ma_short": ma_short,
            "ma_long": ma_long,
            "lookback_short": TREND_SHORT_LOOKBACK,
            "lookback_long": TREND_LONG_LOOKBACK,
        },
        "breadth": {
            "value": breadth_value,
            "lookback": BREADTH_LOOKBACK,
            **breadth_snapshot,
        },
    }

    inputs_snapshot = {
        "ny_date": ny_date,
        "last_date": last_date,
        "spy_close": spy_close,
        "vol_returns": vol_returns,
        "drawdown_closes": drawdown_closes,
        "trend_ma_short": ma_short,
        "trend_ma_long": ma_long,
        "breadth": breadth_snapshot,
    }

    feature_set = RegimeFeatureSet(
        ny_date=ny_date,
        last_date=last_date,
        volatility=vol,
        drawdown=drawdown,
        trend=trend,
        breadth=breadth_value,
        signals=signals,
        inputs_snapshot=inputs_snapshot,
    )

    return RegimeFeatureResult(
        ok=True,
        feature_set=feature_set,
        reason_codes=[],
        inputs_snapshot=inputs_snapshot,
    )


def iter_ny_dates(start: str, end: str) -> Iterable[str]:
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    for dt in pd.date_range(start_dt, end_dt, freq="D"):
        yield dt.date().isoformat()

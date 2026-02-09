from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from typing import Any, Iterable

import pandas as pd

DEFAULT_VOL_LOOKBACK = 20
DEFAULT_DRAWDOWN_LOOKBACK = 63
DEFAULT_TREND_SHORT_LOOKBACK = 50
DEFAULT_TREND_LONG_LOOKBACK = 200
DEFAULT_BREADTH_LOOKBACK = 50
DEFAULT_MIN_BREADTH_SYMBOLS = 20

ENV_VOL_LOOKBACK = "REGIME_E1_VOL_LOOKBACK"
ENV_DRAWDOWN_LOOKBACK = "REGIME_E1_DRAWDOWN_LOOKBACK"
ENV_TREND_SHORT_LOOKBACK = "REGIME_E1_TREND_SHORT_LOOKBACK"
ENV_TREND_LONG_LOOKBACK = "REGIME_E1_TREND_LONG_LOOKBACK"
ENV_BREADTH_LOOKBACK = "REGIME_E1_BREADTH_LOOKBACK"
ENV_MIN_BREADTH_SYMBOLS = "REGIME_E1_MIN_BREADTH_SYMBOLS"


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


@dataclass(frozen=True)
class RegimeLookbacks:
    vol: int
    drawdown: int
    trend_short: int
    trend_long: int
    breadth: int
    min_breadth_symbols: int


def _round(value: float, places: int = 6) -> float:
    return round(float(value), places)


def _env_positive_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return default
    return parsed


def _resolve_lookbacks() -> RegimeLookbacks:
    trend_long = _env_positive_int(
        ENV_TREND_LONG_LOOKBACK, DEFAULT_TREND_LONG_LOOKBACK
    )
    trend_short = _env_positive_int(
        ENV_TREND_SHORT_LOOKBACK, DEFAULT_TREND_SHORT_LOOKBACK
    )
    # Keep trend windows coherent even when env overrides are misconfigured.
    trend_short = min(trend_short, trend_long)
    return RegimeLookbacks(
        vol=_env_positive_int(ENV_VOL_LOOKBACK, DEFAULT_VOL_LOOKBACK),
        drawdown=_env_positive_int(ENV_DRAWDOWN_LOOKBACK, DEFAULT_DRAWDOWN_LOOKBACK),
        trend_short=trend_short,
        trend_long=trend_long,
        breadth=_env_positive_int(ENV_BREADTH_LOOKBACK, DEFAULT_BREADTH_LOOKBACK),
        min_breadth_symbols=_env_positive_int(
            ENV_MIN_BREADTH_SYMBOLS, DEFAULT_MIN_BREADTH_SYMBOLS
        ),
    )


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


def _compute_volatility(
    closes: pd.Series, reasons: list[str], *, lookback: int
) -> tuple[float | None, list[float]]:
    returns = closes.pct_change().dropna()
    window = _series_tail(returns, lookback)
    if not _require_length(window, lookback, "insufficient_vol_history", reasons):
        return None, []
    vol = window.std(ddof=0) * (252 ** 0.5)
    return _round(vol), [_round(val) for val in window.tolist()]


def _compute_drawdown(
    closes: pd.Series, reasons: list[str], *, lookback: int
) -> tuple[float | None, list[float]]:
    window = _series_tail(closes, lookback)
    if not _require_length(window, lookback, "insufficient_drawdown_history", reasons):
        return None, []
    running_max = window.cummax()
    drawdowns = window / running_max - 1.0
    return _round(drawdowns.min()), [_round(val) for val in window.tolist()]


def _compute_trend(
    closes: pd.Series,
    reasons: list[str],
    *,
    short_lookback: int,
    long_lookback: int,
) -> tuple[float | None, float | None, float | None]:
    window_long = _series_tail(closes, long_lookback)
    if not _require_length(window_long, long_lookback, "insufficient_trend_history", reasons):
        return None, None, None
    window_short = _series_tail(closes, short_lookback)
    if not _require_length(
        window_short, short_lookback, "insufficient_trend_short_history", reasons
    ):
        return None, None, None
    ma_short = window_short.mean()
    ma_long = window_long.mean()
    if ma_long == 0:
        reasons.append("invalid_trend_ma")
        return None, None, None
    trend = ma_short / ma_long - 1.0
    return _round(trend), _round(ma_short), _round(ma_long)


def _breadth_fraction(
    df: pd.DataFrame,
    ny_date: str,
    *,
    breadth_lookback: int | None = None,
    min_breadth_symbols: int | None = None,
) -> tuple[float | None, dict[str, Any], str | None]:
    lookback = breadth_lookback or _resolve_lookbacks().breadth
    min_symbols = min_breadth_symbols or _resolve_lookbacks().min_breadth_symbols
    breadth_symbols: list[str] = []
    above_count = 0
    df_sorted = df.sort_values(["symbol", "date"])
    for symbol, history in df_sorted.groupby("symbol", sort=True):
        if len(history) < lookback:
            continue
        closes = history["close"]
        window = closes.iloc[-lookback:]
        ma = window.mean()
        last_close = closes.iloc[-1]
        breadth_symbols.append(symbol)
        if last_close >= ma:
            above_count += 1
    if len(breadth_symbols) < min_symbols:
        return None, {}, "insufficient_breadth_symbols"
    fraction = above_count / len(breadth_symbols)
    return _round(fraction), {
        "method": "above_ma_fraction",
        "symbols_used": breadth_symbols,
        "above_ma_count": above_count,
    }, None


def _breadth_ratio(
    df: pd.DataFrame,
    ny_date: str,
    *,
    breadth_lookback: int | None = None,
) -> tuple[float | None, dict[str, Any], str | None]:
    lookback = breadth_lookback or _resolve_lookbacks().breadth
    spy = _filter_as_of(_symbol_history(df, "SPY"), ny_date)
    iwm = _filter_as_of(_symbol_history(df, "IWM"), ny_date)
    if spy.empty or iwm.empty:
        return None, {}, "missing_breadth_ratio_symbols"
    merged = pd.merge(spy[["date", "close"]], iwm[["date", "close"]], on="date", suffixes=("_spy", "_iwm"))
    merged = merged.sort_values("date")
    if len(merged) < lookback:
        return None, {}, "insufficient_breadth_ratio_history"
    ratio = merged["close_iwm"] / merged["close_spy"]
    window = _series_tail(ratio, lookback)
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
    lookbacks = _resolve_lookbacks()
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
    vol, vol_returns = _compute_volatility(spy_closes, reasons, lookback=lookbacks.vol)
    drawdown, drawdown_closes = _compute_drawdown(
        spy_closes, reasons, lookback=lookbacks.drawdown
    )
    trend, ma_short, ma_long = _compute_trend(
        spy_closes,
        reasons,
        short_lookback=lookbacks.trend_short,
        long_lookback=lookbacks.trend_long,
    )

    breadth_reasons: list[str] = []
    breadth_value, breadth_snapshot, breadth_reason = _breadth_fraction(
        df,
        ny_date,
        breadth_lookback=lookbacks.breadth,
        min_breadth_symbols=lookbacks.min_breadth_symbols,
    )
    if breadth_value is None and breadth_reason:
        breadth_reasons.append(breadth_reason)
    if breadth_value is None:
        breadth_value, breadth_snapshot, breadth_reason = _breadth_ratio(
            df, ny_date, breadth_lookback=lookbacks.breadth
        )
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
            "lookbacks": {
                "vol": lookbacks.vol,
                "drawdown": lookbacks.drawdown,
                "trend_short": lookbacks.trend_short,
                "trend_long": lookbacks.trend_long,
                "breadth": lookbacks.breadth,
                "min_breadth_symbols": lookbacks.min_breadth_symbols,
            },
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
            "lookback": lookbacks.vol,
        },
        "drawdown": {
            "value": drawdown,
            "lookback": lookbacks.drawdown,
        },
        "trend": {
            "value": trend,
            "ma_short": ma_short,
            "ma_long": ma_long,
            "lookback_short": lookbacks.trend_short,
            "lookback_long": lookbacks.trend_long,
        },
        "breadth": {
            "value": breadth_value,
            "lookback": lookbacks.breadth,
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
        "lookbacks": {
            "vol": lookbacks.vol,
            "drawdown": lookbacks.drawdown,
            "trend_short": lookbacks.trend_short,
            "trend_long": lookbacks.trend_long,
            "breadth": lookbacks.breadth,
            "min_breadth_symbols": lookbacks.min_breadth_symbols,
        },
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

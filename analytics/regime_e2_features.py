from __future__ import annotations

from typing import Any

import pandas as pd

from analytics.regime_e1_features import (
    RegimeFeatureResult,
    RegimeFeatureSet,
    _normalize_columns,
    _filter_as_of,
    _round,
    _series_tail,
    _symbol_history,
    _to_date_string,
    compute_regime_features,
)

DEFAULT_E2_LOOKBACK = 63
DEFAULT_RS_LOOKBACK = 20


def _credit_spread_z(
    df: pd.DataFrame, ny_date: str, lookback: int
) -> float:
    """HYG/LQD ratio z-score. Positive z = tight spreads = risk-on."""
    hyg = _filter_as_of(_symbol_history(df, "HYG"), ny_date)
    lqd = _filter_as_of(_symbol_history(df, "LQD"), ny_date)
    if hyg.empty or lqd.empty:
        return 0.0
    merged = pd.merge(
        hyg[["date", "close"]],
        lqd[["date", "close"]],
        on="date",
        suffixes=("_hyg", "_lqd"),
    )
    merged = merged.sort_values("date")
    if len(merged) < lookback:
        return 0.0
    ratio = merged["close_hyg"] / merged["close_lqd"]
    window = _series_tail(ratio, lookback)
    std = window.std(ddof=0)
    if std == 0:
        return 0.0
    z = (window.iloc[-1] - window.mean()) / std
    return _round(z)


def _relative_strength(
    df: pd.DataFrame,
    symbol: str,
    spy_ticker: str,
    ny_date: str,
    lookback: int,
) -> float:
    """20-day relative strength of *symbol* vs SPY (return difference)."""
    sym = _filter_as_of(_symbol_history(df, symbol), ny_date)
    spy = _filter_as_of(_symbol_history(df, spy_ticker), ny_date)
    if sym.empty or spy.empty:
        return 0.0
    merged = pd.merge(
        sym[["date", "close"]],
        spy[["date", "close"]],
        on="date",
        suffixes=(f"_{symbol.lower()}", "_spy"),
    )
    merged = merged.sort_values("date")
    if len(merged) < lookback + 1:
        return 0.0
    sym_close = merged[f"close_{symbol.lower()}"]
    spy_close = merged["close_spy"]
    sym_ret = sym_close.iloc[-1] / sym_close.iloc[-lookback] - 1.0
    spy_ret = spy_close.iloc[-1] / spy_close.iloc[-lookback] - 1.0
    return _round(sym_ret - spy_ret)


def compute_e2_features(
    history: pd.DataFrame,
    ny_date: str,
    *,
    spy_ticker: str = "SPY",
    lookback: int = DEFAULT_E2_LOOKBACK,
) -> RegimeFeatureResult:
    """Compute E2 regime features (E1 base + credit/cross-asset signals)."""
    e1_result = compute_regime_features(history, ny_date)
    if not e1_result.ok:
        return e1_result

    e1 = e1_result.feature_set
    assert e1 is not None

    try:
        df = _normalize_columns(history)
    except ValueError:
        return e1_result
    df = _filter_as_of(df, ny_date)

    credit_z = _credit_spread_z(df, ny_date, lookback)
    gld_rs = _relative_strength(df, "GLD", spy_ticker, ny_date, DEFAULT_RS_LOOKBACK)
    tlt_rs = _relative_strength(df, "TLT", spy_ticker, ny_date, DEFAULT_RS_LOOKBACK)

    signals: dict[str, Any] = {**e1.signals}
    signals["credit_spread"] = {"credit_spread_z": credit_z, "lookback": lookback}
    signals["gld_relative_strength"] = {"value": gld_rs, "lookback": DEFAULT_RS_LOOKBACK}
    signals["tlt_relative_strength"] = {"value": tlt_rs, "lookback": DEFAULT_RS_LOOKBACK}

    inputs_snapshot: dict[str, Any] = {**e1.inputs_snapshot}
    inputs_snapshot["e2_lookback"] = lookback
    inputs_snapshot["credit_spread_z"] = credit_z
    inputs_snapshot["gld_relative_strength"] = gld_rs
    inputs_snapshot["tlt_relative_strength"] = tlt_rs

    feature_set = RegimeFeatureSet(
        ny_date=e1.ny_date,
        last_date=e1.last_date,
        volatility=e1.volatility,
        drawdown=e1.drawdown,
        trend=e1.trend,
        breadth=e1.breadth,
        signals=signals,
        inputs_snapshot=inputs_snapshot,
        credit_spread_z=credit_z,
        vix_term_structure=0.0,
        gld_relative_strength=gld_rs,
        tlt_relative_strength=tlt_rs,
    )

    return RegimeFeatureResult(
        ok=True,
        feature_set=feature_set,
        reason_codes=[],
        inputs_snapshot=inputs_snapshot,
    )

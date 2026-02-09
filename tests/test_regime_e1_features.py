from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

pytestmark = pytest.mark.requires_pandas

from analytics import regime_e1_features


def _make_breadth_history(symbols: list[str], days: int = 55) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=days, freq="B")
    rows = []
    for symbol in symbols:
        if symbol.endswith("UP"):
            price = 100.0
            step = 1.0
        else:
            price = 200.0
            step = -1.0
        for dt in dates:
            rows.append({
                "date": dt,
                "symbol": symbol,
                "close": price,
            })
            price += step
    return pd.DataFrame(rows)


def _make_feature_history(symbols: list[str], days: int = 12) -> pd.DataFrame:
    dates = pd.date_range("2026-01-02", periods=days, freq="B")
    rows = []
    for idx, symbol in enumerate(symbols):
        price = 100.0 + (idx * 2.0)
        for dt in dates:
            price *= 1.002
            rows.append({"Date": dt, "Ticker": symbol, "Close": price})
    return pd.DataFrame(rows)


def test_breadth_fraction_expected_values() -> None:
    up_symbols = [f"SYM{i:02d}UP" for i in range(10)]
    down_symbols = [f"SYM{i:02d}DN" for i in range(10)]
    symbols = up_symbols + down_symbols
    history = _make_breadth_history(symbols)
    ny_date = history["date"].max().date().isoformat()

    fraction, snapshot, reason = regime_e1_features._breadth_fraction(history, ny_date)

    assert reason is None
    assert fraction == 0.5
    assert snapshot["method"] == "above_ma_fraction"
    assert snapshot["above_ma_count"] == len(up_symbols)
    assert snapshot["symbols_used"] == sorted(symbols)


def test_breadth_fraction_does_not_call_symbol_history(monkeypatch: pytest.MonkeyPatch) -> None:
    symbols = [f"SYM{i:02d}UP" for i in range(20)]
    history = _make_breadth_history(symbols)
    ny_date = history["date"].max().date().isoformat()

    def _raise_symbol_history(*_args: object, **_kwargs: object) -> pd.DataFrame:
        raise AssertionError("_symbol_history should not be called")

    monkeypatch.setattr(regime_e1_features, "_symbol_history", _raise_symbol_history)

    fraction, snapshot, reason = regime_e1_features._breadth_fraction(history, ny_date)

    assert reason is None
    assert fraction == 1.0
    assert snapshot["above_ma_count"] == len(symbols)


def test_resolve_lookbacks_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(regime_e1_features.ENV_VOL_LOOKBACK, "6")
    monkeypatch.setenv(regime_e1_features.ENV_DRAWDOWN_LOOKBACK, "8")
    monkeypatch.setenv(regime_e1_features.ENV_TREND_SHORT_LOOKBACK, "5")
    monkeypatch.setenv(regime_e1_features.ENV_TREND_LONG_LOOKBACK, "11")
    monkeypatch.setenv(regime_e1_features.ENV_BREADTH_LOOKBACK, "7")
    monkeypatch.setenv(regime_e1_features.ENV_MIN_BREADTH_SYMBOLS, "3")

    lookbacks = regime_e1_features._resolve_lookbacks()

    assert lookbacks.vol == 6
    assert lookbacks.drawdown == 8
    assert lookbacks.trend_short == 5
    assert lookbacks.trend_long == 11
    assert lookbacks.breadth == 7
    assert lookbacks.min_breadth_symbols == 3


def test_resolve_lookbacks_invalid_values_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(regime_e1_features.ENV_VOL_LOOKBACK, "-1")
    monkeypatch.setenv(regime_e1_features.ENV_DRAWDOWN_LOOKBACK, "bad")
    monkeypatch.setenv(regime_e1_features.ENV_TREND_SHORT_LOOKBACK, "500")
    monkeypatch.setenv(regime_e1_features.ENV_TREND_LONG_LOOKBACK, "10")
    monkeypatch.setenv(regime_e1_features.ENV_BREADTH_LOOKBACK, "0")
    monkeypatch.setenv(regime_e1_features.ENV_MIN_BREADTH_SYMBOLS, "x")

    lookbacks = regime_e1_features._resolve_lookbacks()

    assert lookbacks.vol == regime_e1_features.DEFAULT_VOL_LOOKBACK
    assert lookbacks.drawdown == regime_e1_features.DEFAULT_DRAWDOWN_LOOKBACK
    assert lookbacks.trend_short == 10
    assert lookbacks.trend_long == 10
    assert lookbacks.breadth == regime_e1_features.DEFAULT_BREADTH_LOOKBACK
    assert (
        lookbacks.min_breadth_symbols
        == regime_e1_features.DEFAULT_MIN_BREADTH_SYMBOLS
    )


def test_compute_regime_features_short_history_with_env_lookbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = _make_feature_history(["SPY", "IWM"], days=12)
    ny_date = history["Date"].max().date().isoformat()

    monkeypatch.setenv(regime_e1_features.ENV_VOL_LOOKBACK, "5")
    monkeypatch.setenv(regime_e1_features.ENV_DRAWDOWN_LOOKBACK, "6")
    monkeypatch.setenv(regime_e1_features.ENV_TREND_SHORT_LOOKBACK, "5")
    monkeypatch.setenv(regime_e1_features.ENV_TREND_LONG_LOOKBACK, "8")
    monkeypatch.setenv(regime_e1_features.ENV_BREADTH_LOOKBACK, "5")
    monkeypatch.setenv(regime_e1_features.ENV_MIN_BREADTH_SYMBOLS, "2")

    result = regime_e1_features.compute_regime_features(history, ny_date)

    assert result.ok
    assert result.feature_set is not None
    assert result.feature_set.signals["volatility"]["lookback"] == 5
    assert result.feature_set.signals["drawdown"]["lookback"] == 6
    assert result.feature_set.signals["trend"]["lookback_short"] == 5
    assert result.feature_set.signals["trend"]["lookback_long"] == 8
    assert result.feature_set.signals["breadth"]["lookback"] == 5

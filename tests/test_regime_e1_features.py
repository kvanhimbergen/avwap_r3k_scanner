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

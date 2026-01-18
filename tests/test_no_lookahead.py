import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from setup_context import load_setup_rules
from config import cfg
import scan_engine


def _make_ohlcv(start: str, periods: int) -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=periods, freq="D")
    close = np.linspace(100.0, 110.0, periods)
    data = {
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": np.full(periods, 1_000_000.0),
    }
    return pd.DataFrame(data, index=dates)


def test_scan_does_not_use_future_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "MIN_AVG_DOLLAR_VOL", 0.0)
    monkeypatch.setattr(cfg, "MIN_PRICE", 0.0)

    df = _make_ohlcv("2024-01-01", 130)
    as_of_dt = df.index[-2]

    df_with_future = df.copy()
    df_with_future.iloc[-1] = {
        "Open": 300.0,
        "High": 310.0,
        "Low": 290.0,
        "Close": 305.0,
        "Volume": 5_000_000.0,
    }

    setup_rules = load_setup_rules()
    result = scan_engine.build_candidate_row(
        df_with_future,
        "TEST",
        "TestSector",
        setup_rules,
        as_of_dt=as_of_dt,
        direction="Long",
    )
    assert result is not None
    assert result["Price"] == round(float(df.loc[as_of_dt, "Close"]), 2)

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
    close = np.linspace(50.0, 60.0, periods)
    data = {
        "Open": close - 0.25,
        "High": close + 0.75,
        "Low": close - 0.75,
        "Close": close,
        "Volume": np.full(periods, 1_500_000.0),
    }
    return pd.DataFrame(data, index=dates)


def test_candidate_generation_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "MIN_AVG_DOLLAR_VOL", 0.0)
    monkeypatch.setattr(cfg, "MIN_PRICE", 0.0)
    monkeypatch.setattr(cfg, "BACKTEST_RANDOM_SEED", 123)

    np.random.seed(cfg.BACKTEST_RANDOM_SEED)

    df = _make_ohlcv("2024-02-01", 130)
    setup_rules = load_setup_rules()
    as_of_dt = df.index[-1]

    first = scan_engine.build_candidate_row(
        df,
        "TEST",
        "TestSector",
        setup_rules,
        as_of_dt=as_of_dt,
        direction="Long",
    )
    second = scan_engine.build_candidate_row(
        df,
        "TEST",
        "TestSector",
        setup_rules,
        as_of_dt=as_of_dt,
        direction="Long",
    )

    assert first == second

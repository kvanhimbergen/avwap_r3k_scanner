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
    as_of_dt = pd.Timestamp("2024-04-06")
    assert as_of_dt.weekday() == 5

    def _fake_setup_context(*_args, **_kwargs):
        return type(
            "SetupContextStub",
            (),
            {
                "vwap_control": "inside",
                "vwap_reclaim": "none",
                "vwap_acceptance": "accepted",
                "vwap_dist_pct": 1.23,
                "avwap_control": "inside",
                "avwap_reclaim": "none",
                "avwap_acceptance": "accepted",
                "avwap_dist_pct": 2.34,
                "extension_state": "neutral",
                "gap_reset": "none",
                "structure_state": "neutral",
            },
        )()

    monkeypatch.setattr(
        scan_engine,
        "shannon_quality_gates",
        lambda *_args, **_kwargs: {"TrendTier": "A"},
    )
    monkeypatch.setattr(
        scan_engine,
        "pick_best_anchor",
        lambda *_args, **_kwargs: ("TestAnchor", 100.0, 0.01, 50.0, 2.0),
    )
    monkeypatch.setattr(
        scan_engine,
        "get_pivot_targets",
        lambda *_args, **_kwargs: (111.0, 122.0),
    )
    monkeypatch.setattr(scan_engine, "compute_setup_context", _fake_setup_context)

    df_with_future = df.copy()
    df_with_future.iloc[-1] = {
        "Open": 300.0,
        "High": 310.0,
        "Low": 290.0,
        "Close": 305.0,
        "Volume": 5_000_000.0,
    }

    setup_rules = load_setup_rules()
    base_result = scan_engine.build_candidate_row(
        df,
        "TEST",
        "TestSector",
        setup_rules,
        as_of_dt=as_of_dt,
        direction="Long",
    )
    future_result = scan_engine.build_candidate_row(
        df_with_future,
        "TEST",
        "TestSector",
        setup_rules,
        as_of_dt=as_of_dt,
        direction="Long",
    )
    assert base_result is not None
    assert future_result is not None
    assert base_result["Price"] == round(float(df.loc[as_of_dt, "Close"]), 2)

    for key in (
        "Price",
        "Entry_Level",
        "Entry_DistPct",
        "Stop_Loss",
        "Target_R1",
        "Target_R2",
        "TrendTier",
        "TrendScore",
        "AVWAP_Slope",
    ):
        assert base_result[key] == future_result[key]

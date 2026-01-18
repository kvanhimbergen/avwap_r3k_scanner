import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from setup_context import load_setup_rules
import scan_engine


def _make_ohlcv(start: str, periods: int) -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=periods, freq="D")
    close = np.linspace(120.0, 130.0, periods)
    data = {
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": np.full(periods, 2_000_000.0),
    }
    return pd.DataFrame(data, index=dates)


def test_scan_engine_schema_matches_output() -> None:
    df = _make_ohlcv("2024-03-01", 130)
    setup_rules = load_setup_rules()
    as_of_dt = df.index[-1]

    row = scan_engine.build_candidate_row(
        df,
        "TEST",
        "TestSector",
        setup_rules,
        as_of_dt=as_of_dt,
        direction="Long",
    )
    assert row is not None

    out = scan_engine._build_candidates_dataframe([row])

    assert out.columns.tolist() == scan_engine.CANDIDATE_COLUMNS

    expected_dtypes = {
        "SchemaVersion": "int64",
        "ScanDate": "object",
        "Symbol": "object",
        "Direction": "object",
        "TrendTier": "object",
        "Price": "float64",
        "Entry_Level": "float64",
        "Entry_DistPct": "float64",
        "Stop_Loss": "float64",
        "Target_R1": "float64",
        "Target_R2": "float64",
        "TrendScore": "float64",
        "Sector": "object",
        "Anchor": "object",
        "AVWAP_Slope": "float64",
        "Setup_VWAP_Control": "object",
        "Setup_VWAP_Reclaim": "object",
        "Setup_VWAP_Acceptance": "object",
        "Setup_VWAP_DistPct": "float64",
        "Setup_AVWAP_Control": "object",
        "Setup_AVWAP_Reclaim": "object",
        "Setup_AVWAP_Acceptance": "object",
        "Setup_AVWAP_DistPct": "float64",
        "Setup_Extension_State": "object",
        "Setup_Gap_Reset": "object",
        "Setup_Structure_State": "object",
    }

    assert out.dtypes.astype(str).to_dict() == expected_dtypes

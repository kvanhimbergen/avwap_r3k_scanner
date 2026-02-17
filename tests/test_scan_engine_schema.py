import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

pytestmark = [pytest.mark.requires_numpy, pytest.mark.requires_pandas]

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
    # NOTE: This test validates the *output schema* contract, not scan qualification.
    # build_candidate_row() may legitimately return None depending on gating rules.
    # So we provide a minimal valid row that satisfies the schema.
    row = {
        "SchemaVersion": 1,
        "ScanDate": pd.Timestamp(as_of_dt).date().isoformat(),
        "Symbol": "TEST",
        "Direction": "Long",
        "TrendTier": "A",
        "Price": float(df.loc[as_of_dt, "Close"]),
        "Entry_Level": float(df.loc[as_of_dt, "Close"]),
        "Entry_DistPct": 0.0,
        "Stop_Loss": float(df.loc[as_of_dt, "Close"]) - 5.0,
        "Target_R1": float(df.loc[as_of_dt, "Close"]) + 5.0,
        "Target_R2": float(df.loc[as_of_dt, "Close"]) + 10.0,
        "TrendScore": 1.0,
        "Sector": "TestSector",
        "Anchor": "Test",
        "AVWAP_Slope": 0.0,
        "Setup_VWAP_Control": "inside",
        "Setup_VWAP_Reclaim": "none",
        "Setup_VWAP_Acceptance": "accepted",
        "Setup_VWAP_DistPct": 0.0,
        "Setup_AVWAP_Control": "inside",
        "Setup_AVWAP_Reclaim": "none",
        "Setup_AVWAP_Acceptance": "accepted",
        "Setup_AVWAP_DistPct": 0.0,
        "Setup_Extension_State": "neutral",
        "Setup_Gap_Reset": "none",
        "Setup_Structure_State": "neutral",
    }

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
        "TrendScore_Zscore": "float64",
        "TrendScore_Pctile": "float64",
        "DistPct_Zscore": "float64",
        "Composite_Rank": "float64",
    }

    assert out.dtypes.astype(str).to_dict() == expected_dtypes

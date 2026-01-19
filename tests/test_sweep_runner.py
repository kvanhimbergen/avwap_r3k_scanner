from pathlib import Path

import pandas as pd

from backtest_sweep import (
    SUMMARY_COLUMNS,
    build_summary_table,
    compute_data_hash,
    compute_run_id,
    compute_walk_forward_splits,
    expand_grid,
)


def test_run_id_deterministic() -> None:
    params = {"start_date": "2024-01-01", "end_date": "2024-02-01", "slippage_bps": 2.0}
    run_id_a = compute_run_id("abc123", "cfg456", params, "data789")
    run_id_b = compute_run_id("abc123", "cfg456", params, "data789")
    assert run_id_a == run_id_b


def test_expand_grid_order() -> None:
    grid = {"b": [1, 2], "a": ["x", "y"]}
    combos = expand_grid(grid)
    assert combos == [
        {"a": "x", "b": 1},
        {"a": "x", "b": 2},
        {"a": "y", "b": 1},
        {"a": "y", "b": 2},
    ]


def test_walk_forward_single_split_boundaries() -> None:
    trading_days = pd.date_range("2024-01-01", periods=10, freq="D").tolist()
    spec = {"mode": "single", "is_end": "2024-01-05", "oos_end": "2024-01-10"}
    splits = compute_walk_forward_splits(trading_days, spec)
    assert splits == [
        {
            "label": "single",
            "is_start": pd.Timestamp("2024-01-01"),
            "is_end": pd.Timestamp("2024-01-05"),
            "oos_start": pd.Timestamp("2024-01-06"),
            "oos_end": pd.Timestamp("2024-01-10"),
        }
    ]


def test_data_hash_sha256(tmp_path: Path) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"offline-only")
    digest = compute_data_hash(sample)
    assert digest == "9fd013ae4da1272b8095ed5f0640e972860d6a19693270d52e1aa0006a5d3f60"


def test_summary_table_schema() -> None:
    rows = [
        {
            "run_id": "abc",
            "data_label": "ohlcv",
            "data_path": "cache/ohlcv.parquet",
            "data_hash": "hash",
            "start_date": "2024-01-01",
            "end_date": "2024-02-01",
            "entry_model": "next_open",
        }
    ]
    df = build_summary_table(rows)
    assert list(df.columns) == SUMMARY_COLUMNS

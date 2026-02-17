from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from analytics.slippage_model import (
    SlippageEvent,
    aggregate_slippage_by_bucket,
    aggregate_slippage_by_time,
    append_slippage_event,
    classify_liquidity_bucket,
    compute_slippage_bps,
)


# --- compute_slippage_bps ---


def test_slippage_bps_positive() -> None:
    # Actual > ideal => positive slippage (bought higher than expected)
    result = compute_slippage_bps(100.0, 100.05)
    assert result == pytest.approx(5.0)


def test_slippage_bps_negative() -> None:
    # Actual < ideal => negative slippage (price improvement)
    result = compute_slippage_bps(100.0, 99.95)
    assert result == pytest.approx(-5.0)


def test_slippage_bps_zero() -> None:
    result = compute_slippage_bps(100.0, 100.0)
    assert result == pytest.approx(0.0)


def test_slippage_bps_nan_ideal() -> None:
    result = compute_slippage_bps(float("nan"), 100.0)
    assert math.isnan(result)


def test_slippage_bps_nan_actual() -> None:
    result = compute_slippage_bps(100.0, float("nan"))
    assert math.isnan(result)


def test_slippage_bps_zero_ideal_price() -> None:
    result = compute_slippage_bps(0.0, 100.0)
    assert math.isnan(result)


# --- classify_liquidity_bucket ---


def test_liquidity_bucket_mega_exactly_5m() -> None:
    assert classify_liquidity_bucket(5_000_000) == "mega"


def test_liquidity_bucket_mega_above() -> None:
    assert classify_liquidity_bucket(10_000_000) == "mega"


def test_liquidity_bucket_large_exactly_2m() -> None:
    assert classify_liquidity_bucket(2_000_000) == "large"


def test_liquidity_bucket_large_just_below_5m() -> None:
    assert classify_liquidity_bucket(4_999_999) == "large"


def test_liquidity_bucket_mid_exactly_750k() -> None:
    assert classify_liquidity_bucket(750_000) == "mid"


def test_liquidity_bucket_mid_just_below_2m() -> None:
    assert classify_liquidity_bucket(1_999_999) == "mid"


def test_liquidity_bucket_small_below_750k() -> None:
    assert classify_liquidity_bucket(749_999) == "small"


def test_liquidity_bucket_small_zero() -> None:
    assert classify_liquidity_bucket(0) == "small"


# --- append_slippage_event / JSONL ledger ---


def _make_event(**overrides: object) -> SlippageEvent:
    defaults = {
        "schema_version": 1,
        "record_type": "EXECUTION_SLIPPAGE",
        "date_ny": "2024-06-03",
        "symbol": "AAPL",
        "strategy_id": "avwap_mean_reversion",
        "expected_price": 190.50,
        "ideal_fill_price": 190.00,
        "actual_fill_price": 190.10,
        "slippage_bps": 5.26,
        "adv_shares_20d": 6_000_000.0,
        "liquidity_bucket": "mega",
        "fill_ts_utc": "2024-06-03T14:35:00+00:00",
        "time_of_day_bucket": "10:30-11:00",
    }
    defaults.update(overrides)
    return SlippageEvent(**defaults)  # type: ignore[arg-type]


def test_append_creates_jsonl_file(tmp_path: Path) -> None:
    event = _make_event()
    result_path = append_slippage_event(event, repo_root=tmp_path)

    assert result_path.exists()
    assert result_path.name == "2024-06-03.jsonl"
    assert result_path.parent.name == "EXECUTION_SLIPPAGE"

    lines = result_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["record_type"] == "EXECUTION_SLIPPAGE"
    assert record["schema_version"] == 1
    assert record["symbol"] == "AAPL"


def test_append_is_append_only(tmp_path: Path) -> None:
    event1 = _make_event(symbol="AAPL")
    event2 = _make_event(symbol="MSFT")
    append_slippage_event(event1, repo_root=tmp_path)
    append_slippage_event(event2, repo_root=tmp_path)

    path = tmp_path / "ledger" / "EXECUTION_SLIPPAGE" / "2024-06-03.jsonl"
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["symbol"] == "AAPL"
    assert json.loads(lines[1])["symbol"] == "MSFT"


def test_append_stable_json_sort_order(tmp_path: Path) -> None:
    event = _make_event()
    append_slippage_event(event, repo_root=tmp_path)

    path = tmp_path / "ledger" / "EXECUTION_SLIPPAGE" / "2024-06-03.jsonl"
    raw = path.read_text(encoding="utf-8").strip()
    record = json.loads(raw)
    keys = list(record.keys())
    assert keys == sorted(keys), "JSONL keys should be sorted for stable output"


# --- aggregate functions ---


def test_aggregate_by_bucket() -> None:
    events = [
        _make_event(liquidity_bucket="mega", slippage_bps=3.0),
        _make_event(liquidity_bucket="mega", slippage_bps=5.0),
        _make_event(liquidity_bucket="large", slippage_bps=10.0),
    ]
    result = aggregate_slippage_by_bucket(events)
    assert result["mega"]["count"] == 2.0
    assert result["mega"]["mean_bps"] == pytest.approx(4.0)
    assert result["large"]["count"] == 1.0
    assert result["large"]["mean_bps"] == pytest.approx(10.0)


def test_aggregate_by_time() -> None:
    events = [
        _make_event(time_of_day_bucket="09:30-10:00", slippage_bps=2.0),
        _make_event(time_of_day_bucket="09:30-10:00", slippage_bps=4.0),
        _make_event(time_of_day_bucket="15:30-16:00", slippage_bps=1.0),
    ]
    result = aggregate_slippage_by_time(events)
    assert result["09:30-10:00"]["count"] == 2.0
    assert result["09:30-10:00"]["mean_bps"] == pytest.approx(3.0)
    assert result["15:30-16:00"]["count"] == 1.0


def test_aggregate_skips_nan_slippage() -> None:
    events = [
        _make_event(liquidity_bucket="mega", slippage_bps=float("nan")),
        _make_event(liquidity_bucket="mega", slippage_bps=5.0),
    ]
    result = aggregate_slippage_by_bucket(events)
    assert result["mega"]["count"] == 1.0
    assert result["mega"]["mean_bps"] == pytest.approx(5.0)

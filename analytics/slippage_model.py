from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


RECORD_TYPE = "EXECUTION_SLIPPAGE"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SlippageEvent:
    schema_version: int
    record_type: str
    date_ny: str
    symbol: str
    strategy_id: str
    expected_price: float
    ideal_fill_price: float
    actual_fill_price: float
    slippage_bps: float
    adv_shares_20d: float
    liquidity_bucket: str
    fill_ts_utc: str
    time_of_day_bucket: str


def classify_liquidity_bucket(adv_shares_20d: float) -> str:
    if adv_shares_20d >= 5_000_000:
        return "mega"
    if adv_shares_20d >= 2_000_000:
        return "large"
    if adv_shares_20d >= 750_000:
        return "mid"
    return "small"


def compute_slippage_bps(ideal_fill_price: float, actual_fill_price: float) -> float:
    if ideal_fill_price == 0.0 or math.isnan(ideal_fill_price):
        return float("nan")
    if math.isnan(actual_fill_price):
        return float("nan")
    return (actual_fill_price - ideal_fill_price) / ideal_fill_price * 10_000


def append_slippage_event(
    event: SlippageEvent,
    *,
    repo_root: Path | str = ".",
) -> Path:
    repo_root = Path(repo_root)
    path = _slippage_path(repo_root, event.date_ny)
    record = asdict(event)
    _append_record(path, record)
    return path


def aggregate_slippage_by_bucket(
    events: list[SlippageEvent],
) -> dict[str, dict[str, float]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for ev in events:
        if not math.isnan(ev.slippage_bps):
            buckets[ev.liquidity_bucket].append(ev.slippage_bps)
    result: dict[str, dict[str, float]] = {}
    for bucket, values in sorted(buckets.items()):
        result[bucket] = {
            "count": float(len(values)),
            "mean_bps": sum(values) / len(values),
            "min_bps": min(values),
            "max_bps": max(values),
        }
    return result


def aggregate_slippage_by_time(
    events: list[SlippageEvent],
) -> dict[str, dict[str, float]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for ev in events:
        if not math.isnan(ev.slippage_bps):
            buckets[ev.time_of_day_bucket].append(ev.slippage_bps)
    result: dict[str, dict[str, float]] = {}
    for bucket, values in sorted(buckets.items()):
        result[bucket] = {
            "count": float(len(values)),
            "mean_bps": sum(values) / len(values),
            "min_bps": min(values),
            "max_bps": max(values),
        }
    return result


def _slippage_path(repo_root: Path, date_ny: str) -> Path:
    return repo_root / "ledger" / "EXECUTION_SLIPPAGE" / f"{date_ny}.jsonl"


def _append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_stable_json_dumps(record) + "\n")


def _stable_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))

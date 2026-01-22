from __future__ import annotations

import json
from pathlib import Path

from analytics.io.ledgers import parse_dry_run_ledger
from analytics.metrics import compute_cumulative_aggregates, compute_daily_aggregates
from analytics.metrics_storage import (
    serialize_cumulative_aggregates,
    serialize_daily_aggregates,
    write_metrics_json,
)
from analytics.reconstruction import reconstruct_trades


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analytics"


def _build_aggregates():
    result = parse_dry_run_ledger(str(FIXTURES_DIR / "dry_run_ledger_reconstruction.json"))
    reconstruction = reconstruct_trades(result.fills)
    dailies = compute_daily_aggregates(reconstruction.trades)
    cumulative = compute_cumulative_aggregates(dailies)
    return dailies, cumulative


def test_metrics_storage_deterministic() -> None:
    dailies, cumulative = _build_aggregates()

    payload_first = {}
    payload_first.update(serialize_daily_aggregates(dailies))
    payload_first.update(serialize_cumulative_aggregates(cumulative))
    payload_second = {}
    payload_second.update(serialize_daily_aggregates(dailies))
    payload_second.update(serialize_cumulative_aggregates(cumulative))

    serialized_first = json.dumps(payload_first, sort_keys=True, separators=(",", ":"))
    serialized_second = json.dumps(payload_second, sort_keys=True, separators=(",", ":"))

    assert serialized_first == serialized_second


def test_write_metrics_json(tmp_path: Path) -> None:
    dailies, cumulative = _build_aggregates()
    payload = {}
    payload.update(serialize_daily_aggregates(dailies))
    payload.update(serialize_cumulative_aggregates(cumulative))
    expected = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    output_path = tmp_path / "metrics.json"
    write_metrics_json(str(output_path), dailies=dailies, cumulative=cumulative)

    assert output_path.read_text() == expected

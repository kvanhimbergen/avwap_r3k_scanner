from __future__ import annotations

import json
from pathlib import Path

from analytics.regime_e1_schemas import RECORD_TYPE_SIGNAL
from analytics.regime_e1_storage import build_record, write_record
from analytics.regime_throttle_writer import run_throttle_writer


def _read_jsonl(path: Path) -> dict:
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_portfolio_throttle_writer_from_regime(tmp_path: Path) -> None:
    regime_payload = {
        "regime_label": "RISK_ON",
        "confidence": 0.9,
        "signals": {},
        "inputs_snapshot": {"ny_date": "2024-01-05"},
        "reason_codes": [],
        "requested_ny_date": "2024-01-06",
        "resolved_ny_date": "2024-01-05",
        "provenance": {"module": "tests.test_portfolio_throttle_writer"},
    }
    regime_record = build_record(
        record_type=RECORD_TYPE_SIGNAL,
        ny_date="2024-01-06",
        as_of_utc="2024-01-06T16:00:00+00:00",
        payload=regime_payload,
    )
    write_record(repo_root=tmp_path, ny_date="2024-01-06", record=regime_record)

    result = run_throttle_writer(
        repo_root=tmp_path,
        ny_date="2024-01-06",
        as_of_utc="2024-01-06T16:00:00+00:00",
        history_path=tmp_path / "missing.parquet",
    )

    ledger_path = Path(result["result"]["ledger_path"])
    assert ledger_path.exists()

    record = _read_jsonl(ledger_path)
    throttle = record["throttle"]
    assert record["requested_ny_date"] == "2024-01-06"
    assert record["resolved_ny_date"] == "2024-01-05"
    assert record["regime_id"] == regime_record["regime_id"]
    assert throttle["risk_multiplier"] == 1.0
    assert throttle["max_new_positions_multiplier"] == 1.0


def test_portfolio_throttle_writer_missing_regime(tmp_path: Path) -> None:
    result = run_throttle_writer(
        repo_root=tmp_path,
        ny_date="2024-01-06",
        as_of_utc="2024-01-06T16:00:00+00:00",
        history_path=tmp_path / "missing.parquet",
    )

    ledger_path = Path(result["result"]["ledger_path"])
    record = _read_jsonl(ledger_path)
    throttle = record["throttle"]
    assert throttle["risk_multiplier"] == 0.0
    assert throttle["max_new_positions_multiplier"] == 0.0
    assert throttle["reasons"] == ["missing_regime", "missing_regime_ledger"]

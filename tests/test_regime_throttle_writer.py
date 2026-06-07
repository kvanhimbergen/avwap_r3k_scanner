from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analytics.regime_e1_schemas import (
    RECORD_TYPE_SIGNAL,
    RECORD_TYPE_SKIPPED,
    build_regime_id,
)
from analytics.regime_e1_storage import ledger_path as regime_ledger_path
from analytics.regime_throttle_writer import (
    RECORD_TYPE_THROTTLE,
    run_throttle_writer,
)


def _write_signal_record(
    repo_root: Path,
    ny_date: str,
    *,
    regime_label: str = "RISK_ON",
    confidence: float = 0.85,
    resolved_ny_date: str | None = None,
    record_type: str = RECORD_TYPE_SIGNAL,
    reason_codes: list[str] | None = None,
) -> str:
    """Append a regime ledger record and return its regime_id."""
    path = regime_ledger_path(repo_root, ny_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "record_type": record_type,
        "schema_version": 1,
        "ny_date": ny_date,
        "as_of_utc": f"{ny_date}T16:00:00+00:00",
        "regime_label": regime_label,
        "confidence": confidence,
        "requested_ny_date": ny_date,
        "resolved_ny_date": resolved_ny_date or ny_date,
        "reason_codes": reason_codes or [],
    }
    regime_id = build_regime_id(payload)
    payload["regime_id"] = regime_id
    with path.open("a") as f:
        f.write(json.dumps(payload, sort_keys=True) + "\n")
    return regime_id


def _write_minimal_history(path: Path) -> None:
    history = pd.DataFrame(
        {
            "Date": ["2026-03-02", "2026-03-03"],
            "Ticker": ["SPY", "SPY"],
            "Close": [470.0, 472.0],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    history.to_parquet(path, index=False)


def _read_throttle_records(repo_root: Path, ny_date: str) -> list[dict[str, Any]]:
    path = repo_root / "ledger" / "PORTFOLIO_THROTTLE" / f"{ny_date}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_writes_risk_on_throttle_from_signal(tmp_path: Path) -> None:
    ny_date = "2026-03-03"
    history_path = tmp_path / "cache" / "ohlcv_history.parquet"
    _write_minimal_history(history_path)
    _write_signal_record(tmp_path, ny_date, regime_label="RISK_ON", confidence=0.85)

    result = run_throttle_writer(
        repo_root=tmp_path,
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        history_path=history_path,
    )

    assert result["status"] == "written"
    rec = result["record"]
    assert rec["record_type"] == RECORD_TYPE_THROTTLE
    assert rec["throttle"]["regime_label"] == "RISK_ON"
    assert rec["throttle"]["risk_multiplier"] == 1.0
    assert rec["throttle"]["max_new_positions_multiplier"] == 1.0
    assert rec["throttle"]["reasons"] == []


def test_writes_risk_off_throttle(tmp_path: Path) -> None:
    ny_date = "2026-03-03"
    history_path = tmp_path / "cache" / "ohlcv_history.parquet"
    _write_minimal_history(history_path)
    _write_signal_record(tmp_path, ny_date, regime_label="RISK_OFF", confidence=0.85)

    result = run_throttle_writer(
        repo_root=tmp_path,
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        history_path=history_path,
    )

    assert result["record"]["throttle"]["risk_multiplier"] == 0.2
    assert result["record"]["throttle"]["max_new_positions_multiplier"] == 0.3


# ---------------------------------------------------------------------------
# Low-confidence haircut — the path that's been actively firing in production
# ---------------------------------------------------------------------------

def test_low_confidence_haircut_halves_multipliers(tmp_path: Path) -> None:
    ny_date = "2026-03-03"
    history_path = tmp_path / "cache" / "ohlcv_history.parquet"
    _write_minimal_history(history_path)
    _write_signal_record(tmp_path, ny_date, regime_label="NEUTRAL", confidence=0.4)

    result = run_throttle_writer(
        repo_root=tmp_path,
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        history_path=history_path,
    )

    throttle = result["record"]["throttle"]
    # NEUTRAL base is (0.6, 0.7) → halved by low-confidence haircut.
    assert throttle["risk_multiplier"] == pytest.approx(0.3)
    assert throttle["max_new_positions_multiplier"] == pytest.approx(0.35)
    assert "low_confidence_haircut" in throttle["reasons"]


# ---------------------------------------------------------------------------
# Missing / malformed ledger
# ---------------------------------------------------------------------------

def test_missing_regime_ledger_falls_back_to_zero_multipliers(tmp_path: Path) -> None:
    ny_date = "2026-03-03"
    history_path = tmp_path / "cache" / "ohlcv_history.parquet"
    _write_minimal_history(history_path)
    # No regime ledger written.

    result = run_throttle_writer(
        repo_root=tmp_path,
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        history_path=history_path,
    )

    throttle = result["record"]["throttle"]
    assert throttle["risk_multiplier"] == 0.0
    assert throttle["max_new_positions_multiplier"] == 0.0
    assert "missing_regime_ledger" in throttle["reasons"]
    assert "unknown_regime" in throttle["reasons"]


def test_skipped_regime_record_propagates_reason(tmp_path: Path) -> None:
    ny_date = "2026-03-03"
    history_path = tmp_path / "cache" / "ohlcv_history.parquet"
    _write_minimal_history(history_path)
    _write_signal_record(
        tmp_path,
        ny_date,
        regime_label="RISK_ON",  # ignored because record_type is SKIPPED
        confidence=0.85,
        record_type=RECORD_TYPE_SKIPPED,
        reason_codes=["excessive_price_staleness"],
    )

    result = run_throttle_writer(
        repo_root=tmp_path,
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        history_path=history_path,
    )

    assert "regime_record_skipped" in result["record"]["throttle"]["reasons"]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_second_run_with_same_regime_id_is_idempotent(tmp_path: Path) -> None:
    ny_date = "2026-03-03"
    history_path = tmp_path / "cache" / "ohlcv_history.parquet"
    _write_minimal_history(history_path)
    _write_signal_record(tmp_path, ny_date, regime_label="RISK_ON", confidence=0.85)

    first = run_throttle_writer(
        repo_root=tmp_path,
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        history_path=history_path,
    )
    second = run_throttle_writer(
        repo_root=tmp_path,
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        history_path=history_path,
    )

    assert first["status"] == "written"
    assert second["status"] == "skipped"
    records = _read_throttle_records(tmp_path, ny_date)
    assert len(records) == 1


def test_appends_record_when_regime_id_changes(tmp_path: Path) -> None:
    ny_date = "2026-03-03"
    history_path = tmp_path / "cache" / "ohlcv_history.parquet"
    _write_minimal_history(history_path)
    _write_signal_record(tmp_path, ny_date, regime_label="RISK_ON", confidence=0.85)
    run_throttle_writer(
        repo_root=tmp_path,
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        history_path=history_path,
    )
    # New regime arrives later in the day — different regime_id.
    _write_signal_record(tmp_path, ny_date, regime_label="RISK_OFF", confidence=0.85)

    second = run_throttle_writer(
        repo_root=tmp_path,
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        history_path=history_path,
    )

    assert second["status"] == "written"
    records = _read_throttle_records(tmp_path, ny_date)
    assert len(records) == 2
    assert records[0]["throttle"]["regime_label"] == "RISK_ON"
    assert records[1]["throttle"]["regime_label"] == "RISK_OFF"

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from analytics.regime_date_resolution import resolve_regime_ny_date
from analytics.regime_e1_schemas import RECORD_TYPE_SIGNAL, RECORD_TYPE_SKIPPED, stable_json_dumps
from analytics.regime_e1_storage import ledger_path as regime_ledger_path
from analytics.regime_policy import regime_to_throttle

RECORD_TYPE_THROTTLE = "PORTFOLIO_THROTTLE"
SCHEMA_VERSION = 1


def _default_as_of_utc(ny_date: str) -> str:
    return f"{ny_date}T16:00:00+00:00"


def _load_history(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_parquet(path, engine="pyarrow")


def _read_latest_regime_record(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, ["missing_regime_ledger"]
    latest_record: dict[str, Any] | None = None
    invalid = False
    with path.open("r") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                invalid = True
                continue
            if data.get("record_type") not in {RECORD_TYPE_SIGNAL, RECORD_TYPE_SKIPPED}:
                continue
            latest_record = data
    if latest_record is None:
        reason = "invalid_regime_ledger" if invalid else "missing_regime_record"
        return None, [reason]
    return latest_record, []


def _throttle_ledger_path(repo_root: Path, ny_date: str) -> Path:
    return repo_root / "ledger" / "PORTFOLIO_THROTTLE" / f"{ny_date}.jsonl"


def _append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(stable_json_dumps(record) + "\n")


def run_throttle_writer(
    *,
    repo_root: Path,
    ny_date: str,
    as_of_utc: str,
    history_path: Path,
) -> dict[str, Any]:
    history = _load_history(history_path)
    resolved_ny_date = ny_date
    if history is not None:
        resolved_ny_date, _, _ = resolve_regime_ny_date(history, ny_date)

    regime_record, ledger_reasons = _read_latest_regime_record(regime_ledger_path(repo_root, ny_date))
    regime_label = None
    confidence = None
    regime_id = None
    additional_reasons: list[str] = []

    if regime_record is not None:
        regime_label = regime_record.get("regime_label")
        confidence = regime_record.get("confidence")
        regime_id = regime_record.get("regime_id")
        resolved_from_record = regime_record.get("resolved_ny_date")
        if resolved_from_record:
            resolved_ny_date = resolved_from_record
        if regime_record.get("record_type") != RECORD_TYPE_SIGNAL:
            additional_reasons.append("regime_record_skipped")
    else:
        additional_reasons.extend(ledger_reasons)

    throttle = regime_to_throttle(regime_label, confidence)
    if additional_reasons:
        throttle["reasons"] = throttle["reasons"] + additional_reasons

    record = {
        "as_of_utc": as_of_utc,
        "requested_ny_date": ny_date,
        "resolved_ny_date": resolved_ny_date,
        "provenance": {"module": "analytics.regime_throttle_writer"},
        "record_type": RECORD_TYPE_THROTTLE,
        "schema_version": SCHEMA_VERSION,
        "regime_id": regime_id,
        "throttle": throttle,
    }
    path = _throttle_ledger_path(repo_root, ny_date)
    _append_record(path, record)
    return {
        "status": "written",
        "record": record,
        "result": {"ledger_path": str(path), "records_written": 1, "skipped": 0},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Write portfolio throttle artifact from Regime E1 ledger")
    parser.add_argument("--ny-date", required=True, help="NY date (YYYY-MM-DD)")
    parser.add_argument("--as-of-utc", default=None, help="UTC timestamp (ISO)")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument(
        "--history-path",
        default="cache/ohlcv_history.parquet",
        help="Path to local OHLCV history parquet",
    )
    args = parser.parse_args()

    ny_date = args.ny_date
    as_of_utc = args.as_of_utc or _default_as_of_utc(ny_date)
    repo_root = Path(args.repo_root).resolve()
    history_path = Path(args.history_path)

    result = run_throttle_writer(
        repo_root=repo_root,
        ny_date=ny_date,
        as_of_utc=as_of_utc,
        history_path=history_path,
    )

    record = result["record"]
    throttle = record["throttle"]
    print(f"status={result['status']}")
    print(f"ledger_path={result['result']['ledger_path']}")
    print(f"resolved_ny_date={record.get('resolved_ny_date')}")
    print(f"regime_label={throttle.get('regime_label')}")
    print(f"risk_multiplier={throttle.get('risk_multiplier')}")


if __name__ == "__main__":
    main()

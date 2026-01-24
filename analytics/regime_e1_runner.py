from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from analytics.regime_e1_classifier import classify_regime
from analytics.regime_date_resolution import resolve_regime_ny_date
from analytics.regime_e1_features import compute_regime_features
from analytics.regime_e1_schemas import RECORD_TYPE_SIGNAL, RECORD_TYPE_SKIPPED
from analytics.regime_e1_storage import build_record, write_record


def _default_as_of_utc(ny_date: str) -> str:
    return f"{ny_date}T16:00:00+00:00"


def _load_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"history parquet missing: {path}")
    return pd.read_parquet(path, engine="pyarrow")


def run_regime_e1(*, repo_root: Path, ny_date: str, as_of_utc: str, history_path: Path) -> dict:
    try:
        history = _load_history(history_path)
    except FileNotFoundError:
        payload = {
            "reason_codes": ["missing_history_path"],
            "inputs_snapshot": {
                "ny_date": ny_date,
                "history_path": str(history_path),
            },
            "requested_ny_date": ny_date,
            "resolved_ny_date": ny_date,
            "provenance": {"module": "analytics.regime_e1_runner"},
        }
        record = build_record(
            record_type=RECORD_TYPE_SKIPPED,
            ny_date=ny_date,
            as_of_utc=as_of_utc,
            payload=payload,
        )
        result = write_record(repo_root=repo_root, ny_date=ny_date, record=record)
        return {
            "status": "skipped",
            "record": record,
            "result": asdict(result),
        }

    resolved_ny_date, resolution_reasons, _ = resolve_regime_ny_date(history, ny_date)
    feature_result = compute_regime_features(history, resolved_ny_date)
    if not feature_result.ok or feature_result.feature_set is None:
        reason_codes = resolution_reasons + feature_result.reason_codes
        payload = {
            "reason_codes": reason_codes,
            "inputs_snapshot": feature_result.inputs_snapshot,
            "requested_ny_date": ny_date,
            "resolved_ny_date": resolved_ny_date,
            "provenance": {"module": "analytics.regime_e1_runner"},
        }
        record = build_record(
            record_type=RECORD_TYPE_SKIPPED,
            ny_date=ny_date,
            as_of_utc=as_of_utc,
            payload=payload,
        )
        result = write_record(repo_root=repo_root, ny_date=ny_date, record=record)
        return {
            "status": "skipped",
            "record": record,
            "result": asdict(result),
        }

    classification = classify_regime(feature_result.feature_set)
    reason_codes = resolution_reasons + classification.reason_codes
    payload = {
        "regime_label": classification.regime_label,
        "confidence": classification.confidence,
        "signals": classification.signals,
        "inputs_snapshot": classification.inputs_snapshot,
        "reason_codes": reason_codes,
        "requested_ny_date": ny_date,
        "resolved_ny_date": resolved_ny_date,
        "provenance": {"module": "analytics.regime_e1_runner"},
    }
    record = build_record(
        record_type=RECORD_TYPE_SIGNAL,
        ny_date=ny_date,
        as_of_utc=as_of_utc,
        payload=payload,
    )
    result = write_record(repo_root=repo_root, ny_date=ny_date, record=record)
    return {
        "status": "written" if result.records_written else "skipped",
        "record": record,
        "result": asdict(result),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Regime E1 classifier for a single NY date")
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

    result = run_regime_e1(
        repo_root=repo_root,
        ny_date=ny_date,
        as_of_utc=as_of_utc,
        history_path=history_path,
    )

    record = result["record"]
    status = result["status"]
    ledger_path = result["result"]["ledger_path"]
    regime_label = record.get("regime_label")
    regime_id = record.get("regime_id")
    print(f"status={status}")
    print(f"ledger_path={ledger_path}")
    print(f"regime_label={regime_label}")
    print(f"regime_id={regime_id}")


if __name__ == "__main__":
    main()

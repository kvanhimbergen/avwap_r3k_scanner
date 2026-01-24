from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from analytics.regime_e1_classifier import classify_regime
from analytics.regime_e1_features import compute_regime_features, iter_ny_dates
from analytics.regime_e1_schemas import RECORD_TYPE_SIGNAL, RECORD_TYPE_SKIPPED
from analytics.regime_e1_storage import build_record, write_record


def _default_as_of_utc(ny_date: str) -> str:
    return f"{ny_date}T16:00:00+00:00"


def _load_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"history parquet missing: {path}")
    return pd.read_parquet(path, engine="pyarrow")


def run_historical(*, repo_root: Path, start: str, end: str, history_path: Path) -> list[dict]:
    results: list[dict] = []
    try:
        history = _load_history(history_path)
    except FileNotFoundError:
        history = None
    for ny_date in iter_ny_dates(start, end):
        as_of_utc = _default_as_of_utc(ny_date)
        if history is None:
            payload = {
                "reason_codes": ["missing_history_path"],
                "inputs_snapshot": {"ny_date": ny_date, "history_path": str(history_path)},
                "provenance": {"module": "analytics.regime_e1_historical"},
            }
            record = build_record(
                record_type=RECORD_TYPE_SKIPPED,
                ny_date=ny_date,
                as_of_utc=as_of_utc,
                payload=payload,
            )
        else:
            feature_result = compute_regime_features(history, ny_date)
            if not feature_result.ok or feature_result.feature_set is None:
                payload = {
                    "reason_codes": feature_result.reason_codes,
                    "inputs_snapshot": feature_result.inputs_snapshot,
                    "provenance": {"module": "analytics.regime_e1_historical"},
                }
                record = build_record(
                    record_type=RECORD_TYPE_SKIPPED,
                    ny_date=ny_date,
                    as_of_utc=as_of_utc,
                    payload=payload,
                )
            else:
                classification = classify_regime(feature_result.feature_set)
                payload = {
                    "regime_label": classification.regime_label,
                    "confidence": classification.confidence,
                    "signals": classification.signals,
                    "inputs_snapshot": classification.inputs_snapshot,
                    "reason_codes": classification.reason_codes,
                    "provenance": {"module": "analytics.regime_e1_historical"},
                }
                record = build_record(
                    record_type=RECORD_TYPE_SIGNAL,
                    ny_date=ny_date,
                    as_of_utc=as_of_utc,
                    payload=payload,
                )
        write_result = write_record(repo_root=repo_root, ny_date=ny_date, record=record)
        results.append({
            "record": record,
            "result": asdict(write_result),
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Regime E1 classifier across a NY date range")
    parser.add_argument("--start", required=True, help="Start NY date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End NY date (YYYY-MM-DD)")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument(
        "--history-path",
        default="cache/ohlcv_history.parquet",
        help="Path to local OHLCV history parquet",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    history_path = Path(args.history_path)

    results = run_historical(
        repo_root=repo_root,
        start=args.start,
        end=args.end,
        history_path=history_path,
    )

    print(f"records={len(results)}")
    if results:
        last = results[-1]
        record = last["record"]
        write_result = last["result"]
        print(f"last_ny_date={record.get('ny_date')}")
        print(f"last_regime_id={record.get('regime_id')}")
        print(f"ledger_path={write_result.get('ledger_path')}")


if __name__ == "__main__":
    main()

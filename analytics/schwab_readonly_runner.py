from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from analytics.schwab_readonly_adapter import SchwabReadonlyFixtureAdapter
from analytics.schwab_readonly_oauth import load_schwab_readonly_oauth_config
from analytics.schwab_readonly_reconciliation import build_reconciliation_report, write_reconciliation_record
from analytics.schwab_readonly_storage import ny_date_from_as_of, write_snapshot_records


@dataclass(frozen=True)
class SchwabReadonlyRunResult:
    ledger_path: str
    snapshots_written: int
    snapshots_skipped: int
    reconciliation_written: bool
    reconciliation_id: str | None


def _load_fixture_meta(fixture_dir: Path) -> dict:
    meta_path = fixture_dir / "meta.json"
    if not meta_path.exists():
        return {}
    import json

    with meta_path.open("r") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return data


def run_snapshot_and_reconciliation(
    *,
    repo_root: Path,
    fixture_dir: Path,
    book_id: str,
    as_of_utc: str,
    ny_date: str | None = None,
    require_enabled: bool = True,
) -> SchwabReadonlyRunResult:
    config = load_schwab_readonly_oauth_config()
    if require_enabled and not config.enabled:
        raise RuntimeError("SCHWAB_READONLY_ENABLED must be set to run snapshots")

    derived_ny_date = ny_date_from_as_of(as_of_utc)
    if ny_date and ny_date != derived_ny_date:
        raise RuntimeError("ny_date does not match as_of_utc")

    adapter = SchwabReadonlyFixtureAdapter.from_fixture_dir(
        fixture_dir,
        book_id=book_id,
        as_of_utc=as_of_utc,
    )
    account_snapshot, positions_snapshot, orders_snapshot = adapter.load_all_snapshots()

    snapshot_result = write_snapshot_records(
        repo_root=repo_root,
        account_snapshot=account_snapshot,
        positions_snapshot=positions_snapshot,
        orders_snapshot=orders_snapshot,
    )

    ledger_path = Path(snapshot_result.ledger_path)
    report = build_reconciliation_report(ledger_path=ledger_path)
    reconciliation_result = write_reconciliation_record(ledger_path=ledger_path, report=report)

    return SchwabReadonlyRunResult(
        ledger_path=snapshot_result.ledger_path,
        snapshots_written=snapshot_result.records_written,
        snapshots_skipped=snapshot_result.skipped,
        reconciliation_written=reconciliation_result.written,
        reconciliation_id=reconciliation_result.reconciliation_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Schwab read-only snapshot ingestion + reconciliation")
    parser.add_argument("--fixture-dir", required=True, help="Path to Schwab read-only fixtures")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--book-id", default="SCHWAB_401K_MANUAL")
    parser.add_argument("--as-of-utc", default="")
    parser.add_argument("--ny-date", default="")

    args = parser.parse_args()
    fixture_dir = Path(args.fixture_dir)
    meta = _load_fixture_meta(fixture_dir)

    as_of_utc = args.as_of_utc.strip() or str(meta.get("as_of_utc") or "").strip()
    if not as_of_utc:
        parser.error("--as-of-utc required (or include as_of_utc in fixtures meta.json)")

    ny_date = args.ny_date.strip() or str(meta.get("ny_date") or "").strip() or None

    result = run_snapshot_and_reconciliation(
        repo_root=Path(args.repo_root),
        fixture_dir=fixture_dir,
        book_id=args.book_id,
        as_of_utc=as_of_utc,
        ny_date=ny_date,
        require_enabled=True,
    )

    print(f"ledger_path={result.ledger_path}")
    print(f"snapshots_written={result.snapshots_written}")
    print(f"snapshots_skipped={result.snapshots_skipped}")
    print(f"reconciliation_written={result.reconciliation_written}")
    print(f"reconciliation_id={result.reconciliation_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read latest Schwab readonly snapshot for v6 live-mode intent diffing.

The post-scan pipeline runs the Schwab readonly sync as step 3, which
appends SCHWAB_READONLY_ACCOUNT_SNAPSHOT + SCHWAB_READONLY_POSITIONS_SNAPSHOT
records to ledger/SCHWAB_401K_MANUAL/<date>.jsonl. v6's live mode reads
those records to compute current dollar positions for intent diff.

Strict freshness: refuses to return data older than `max_stale_bdays`
business days. Stale positions would generate wrong-direction trades.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from utils.freshness import staleness_bdays


LIVE_BOOK_ID = "SCHWAB_401K_MANUAL"


class SchwabPositionsStaleError(RuntimeError):
    """Raised when the latest Schwab snapshot is too old to safely diff against."""


@dataclass(frozen=True)
class LiveBookSnapshot:
    asof: date
    total_equity: float
    cash: float
    positions_dollars: dict[str, float]  # symbol -> market value

    @property
    def positions_pct(self) -> dict[str, float]:
        if self.total_equity <= 0:
            return {}
        return {s: v / self.total_equity for s, v in self.positions_dollars.items()}

    @property
    def cash_pct(self) -> float:
        if self.total_equity <= 0:
            return 0.0
        return self.cash / self.total_equity


def _ledger_path(repo_root: Path, asof: date) -> Path:
    return repo_root / "ledger" / LIVE_BOOK_ID / f"{asof.isoformat()}.jsonl"


def _read_snapshots_for_date(
    path: Path,
) -> tuple[dict | None, dict | None]:
    """Return (account_snapshot, positions_snapshot) — latest of each by
    as_of_utc, or None if missing."""
    if not path.exists():
        return None, None
    account: dict | None = None
    positions: dict | None = None
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = rec.get("record_type")
            if t == "SCHWAB_READONLY_ACCOUNT_SNAPSHOT":
                if account is None or rec.get("as_of_utc", "") > account.get("as_of_utc", ""):
                    account = rec
            elif t == "SCHWAB_READONLY_POSITIONS_SNAPSHOT":
                if positions is None or rec.get("as_of_utc", "") > positions.get("as_of_utc", ""):
                    positions = rec
    return account, positions


def read_latest_snapshot(
    *,
    repo_root: Path,
    asof: date,
    max_stale_bdays: int = 1,
) -> LiveBookSnapshot:
    """Return the latest Schwab snapshot at/before `asof`.

    Walks back day-by-day up to `max_stale_bdays` business days. Raises
    SchwabPositionsStaleError if no usable snapshot exists in that window.

    Pairs account snapshot (equity, cash) with positions snapshot.
    """
    # Walk back; allow up to max_stale_bdays of weekend/holiday skipping
    # plus 1 calendar day for the day-of file not yet existing.
    from datetime import timedelta
    for offset in range(0, max_stale_bdays + 5):
        candidate = asof - timedelta(days=offset)
        path = _ledger_path(repo_root, candidate)
        account, positions = _read_snapshots_for_date(path)
        if account is None or positions is None:
            continue
        # Verify freshness in business days vs requested asof.
        snap_ny_date = date.fromisoformat(str(account.get("ny_date", candidate.isoformat())))
        stale = staleness_bdays(snap_ny_date, asof.isoformat())
        if stale > max_stale_bdays:
            raise SchwabPositionsStaleError(
                f"Latest Schwab snapshot is {snap_ny_date.isoformat()} "
                f"({stale} business days stale > max {max_stale_bdays}). "
                f"Run the Schwab readonly sync before live v6 execution."
            )
        # Parse account fields (stored as strings).
        total_equity = float(account.get("total_value", 0) or 0)
        cash = float(account.get("cash", 0) or 0)
        positions_dollars: dict[str, float] = {}
        for p in positions.get("positions", []):
            sym = str(p.get("symbol", "")).upper()
            mv = float(p.get("market_value", 0) or 0)
            if sym and mv > 0:
                positions_dollars[sym] = positions_dollars.get(sym, 0.0) + mv
        return LiveBookSnapshot(
            asof=snap_ny_date,
            total_equity=total_equity,
            cash=cash,
            positions_dollars=positions_dollars,
        )
    raise SchwabPositionsStaleError(
        f"No Schwab snapshot found in last {max_stale_bdays + 5} days from {asof.isoformat()}. "
        f"Run analytics.schwab_readonly_runner --live --ny-date {asof.isoformat()} first."
    )

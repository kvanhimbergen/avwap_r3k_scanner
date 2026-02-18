#!/usr/bin/env python3
"""Post-scan daily pipeline.

Runs after the daily AVWAP scan completes.  Executes these steps in order:

1. regime_e1_runner       → ledger/REGIME_E1/{date}.jsonl
2. regime_throttle_writer → ledger/PORTFOLIO_THROTTLE/{date}.jsonl
3. s2_letf_orb_aggro      → ledger/STRATEGY_SIGNALS/S2_LETF_ORB_AGGRO/{date}.jsonl
4. raec_401k_coordinator   → ledger/RAEC_REBALANCE/RAEC_401K_COORD/{date}.jsonl
5. schwab_readonly_sync   → (optional) live Schwab account sync

Steps 1→2 are sequential (throttle reads regime output).
Steps 3 and 4 are independent but run sequentially for log clarity.
Step 5 is optional — fails gracefully if credentials are missing or API is down.

Usage:
    python ops/post_scan_pipeline.py                       # auto-detect today (NY)
    python ops/post_scan_pipeline.py --date 2026-02-18     # explicit date
    python ops/post_scan_pipeline.py --dry-run              # suppress Slack posts
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime

from zoneinfo import ZoneInfo

STEPS = [
    {
        "name": "regime_e1_runner",
        "args": lambda date: [
            sys.executable, "-m", "analytics.regime_e1_runner",
            "--ny-date", date,
        ],
    },
    {
        "name": "regime_throttle_writer",
        "args": lambda date: [
            sys.executable, "-m", "analytics.regime_throttle_writer",
            "--ny-date", date,
        ],
    },
    {
        "name": "s2_letf_orb_aggro",
        "args": lambda date: [
            sys.executable, "-m", "strategies.s2_letf_orb_aggro",
            "--asof", date,
        ],
    },
    {
        "name": "raec_401k_coordinator",
        "args": lambda date: [
            sys.executable, "-m", "strategies.raec_401k_coordinator",
            "--asof", date,
        ],
    },
    {
        "name": "schwab_readonly_sync",
        "optional": True,
        "args": lambda date: [
            sys.executable, "-m", "analytics.schwab_readonly_runner",
            "--live",
            "--ny-date", date,
        ],
    },
]


def _ny_today() -> str:
    return datetime.now(tz=ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def run_pipeline(date: str, *, dry_run: bool = False) -> None:
    for i, step in enumerate(STEPS, 1):
        cmd = step["args"](date)
        if dry_run and step["name"] == "raec_401k_coordinator":
            cmd.append("--dry-run")
        label = f"[{i}/{len(STEPS)}] {step['name']}"
        optional = step.get("optional", False)
        print(f"{label}: running ...", flush=True)
        print(f"  cmd: {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            if optional:
                print(f"{label}: SKIPPED (optional, exit {result.returncode})", flush=True)
            else:
                print(f"{label}: FAILED (exit {result.returncode})", flush=True)
                sys.exit(result.returncode)
        else:
            print(f"{label}: OK", flush=True)
    print("Pipeline complete.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-scan daily pipeline")
    parser.add_argument(
        "--date",
        default=None,
        help="NY date (YYYY-MM-DD). Defaults to today in America/New_York.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Suppress Slack posts (passed to coordinator).",
    )
    args = parser.parse_args()
    date = args.date or _ny_today()
    print(f"Post-scan pipeline: date={date} dry_run={args.dry_run}", flush=True)
    run_pipeline(date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

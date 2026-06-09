#!/usr/bin/env python3
"""Post-scan daily pipeline (7 steps).

Runs after the daily AVWAP scan completes.  Executes these steps in order:

1. regime_e1_runner           → ledger/REGIME_E1/{date}.jsonl
2. regime_throttle_writer     → ledger/PORTFOLIO_THROTTLE/{date}.jsonl
3. schwab_readonly_sync       → (optional) live Schwab account sync
4. schwab_seed_allocations    → (optional) seed RAEC state from Schwab positions
5. s2_letf_orb_aggro          → ledger/STRATEGY_SIGNALS/S2_LETF_ORB_AGGRO/{date}.jsonl
6. s2_letf_orb_alpaca         → (optional) bracket orders from S2 candidates (Alpaca paper)
7. raec_401k_coordinator      → ledger/RAEC_REBALANCE/RAEC_401K_COORD/{date}.jsonl

Steps 1-2 are sequential (throttle reads regime output).
Steps 3-4 are optional — if Schwab API is down, RAEC falls back to stale state.
Steps 5-6 are sequential (S2 bracket orders depend on candidate CSV from step 5).

Usage:
    python ops/post_scan_pipeline.py                       # auto-detect today (NY)
    python ops/post_scan_pipeline.py --date 2026-02-18     # explicit date
    python ops/post_scan_pipeline.py --dry-run              # suppress execution
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from zoneinfo import ZoneInfo

from alerts.slack import slack_alert
from utils.freshness import file_mtime_ny_date, staleness_bdays

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCAN_OUTPUT = _REPO_ROOT / "daily_candidates.csv"
_COMPONENT = "PostScan"

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
        "name": "schwab_readonly_sync",
        "optional": True,
        "args": lambda date: [
            sys.executable, "-m", "analytics.schwab_readonly_runner",
            "--live",
            "--ny-date", date,
        ],
    },
    {
        "name": "schwab_seed_allocations",
        "optional": True,
        "args": lambda date: [
            sys.executable, "-m", "analytics.schwab_seed_allocations",
            "--ny-date", date,
        ],
    },
    {
        "name": "s2_letf_orb_aggro",
        "args": lambda date: [
            sys.executable, "-m", "strategies.s2_letf_orb_aggro",
            "--asof", date,
            "--universe-profile", "leveraged_only",
        ],
    },
    {
        "name": "s2_letf_orb_alpaca",
        "optional": True,
        "args": lambda date: [
            sys.executable, "-m", "strategies.s2_letf_orb_alpaca",
            "--asof", date,
        ],
    },
    {
        # v6 LIVE coordinator. Posts executable Schwab tickets to Slack
        # under the component "RAEC_V6" (no [V6 DRY] prefix). Reads the
        # latest Schwab readonly snapshot for current positions.
        # If v6 fails for any reason, the legacy V3-V5 coordinator below
        # is still available as a manual fallback (just re-run it by hand
        # via `python -m strategies.raec_401k_coordinator --asof <date>`).
        "name": "raec_v6_coordinator_live",
        "args": lambda date: [
            sys.executable, "-m", "strategies.raec_v6.coordinator",
            "--asof-date", date,
            "--mode", "live",
        ],
    },
    # NOTE: the legacy V3-V5 coordinator is intentionally NOT in the daily
    # pipeline anymore — v6 above is the primary. Kept as a manual-fallback
    # module so you can still run it on-demand if needed.
]


def _ny_today() -> str:
    return datetime.now(tz=ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def _scan_output_fresh(date: str) -> bool:
    """Return True iff today's scan output exists and has no business-day staleness."""
    if not _SCAN_OUTPUT.exists():
        return False
    return staleness_bdays(file_mtime_ny_date(_SCAN_OUTPUT), date) == 0


def _notify(level: str, title: str, message: str, *, dry_run: bool) -> None:
    """Send a Slack alert unless we're in dry-run."""
    if dry_run:
        return
    slack_alert(level, title, message, component=_COMPONENT)


def run_pipeline(date: str, *, dry_run: bool = False) -> None:
    if not _scan_output_fresh(date):
        msg = f"scan output {_SCAN_OUTPUT} not fresh for {date}; proceeding with stale data"
        print(f"WARNING: {msg}", flush=True)
        _notify("WARNING", "Post-scan: stale scan output", msg, dry_run=dry_run)

    ok: list[str] = []
    skipped: list[tuple[str, int]] = []
    for i, step in enumerate(STEPS, 1):
        cmd = step["args"](date)
        if dry_run and step["name"] in {
            "raec_401k_coordinator", "s2_letf_orb_alpaca",
        }:
            cmd.append("--dry-run")
        if dry_run and step["name"] == "raec_v6_coordinator_live":
            # v6 uses --mode instead of --dry-run; swap live → dry-run.
            if "--mode" in cmd:
                idx = cmd.index("--mode")
                cmd[idx + 1] = "dry-run"
        label = f"[{i}/{len(STEPS)}] {step['name']}"
        optional = step.get("optional", False)
        print(f"{label}: running ...", flush=True)
        print(f"  cmd: {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            if optional:
                print(f"{label}: SKIPPED (optional, exit {result.returncode})", flush=True)
                skipped.append((step["name"], result.returncode))
            else:
                print(f"{label}: FAILED (exit {result.returncode})", flush=True)
                _notify(
                    "ERROR",
                    "Post-scan pipeline FAILED",
                    f"step={step['name']} ({i}/{len(STEPS)})\n"
                    f"exit_code={result.returncode}\n"
                    f"date={date}\n"
                    f"see launchd log for stderr",
                    dry_run=dry_run,
                )
                sys.exit(result.returncode)
        else:
            print(f"{label}: OK", flush=True)
            ok.append(step["name"])

    summary_lines = [
        f"date={date}",
        f"ok={len(ok)}/{len(STEPS)}",
    ]
    if skipped:
        skipped_str = ", ".join(f"{name}(exit {code})" for name, code in skipped)
        summary_lines.append(f"skipped={len(skipped)}: {skipped_str}")
    _notify(
        "WARNING" if skipped else "INFO",
        "Post-scan pipeline OK",
        "\n".join(summary_lines),
        dry_run=dry_run,
    )
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
        help="Suppress orders/posts — passed to raec_401k_coordinator and s2_letf_orb_alpaca only. "
             "Other steps (regime writers, Schwab sync, seed allocations, s2 aggro) always run "
             "with full side effects as they only write local ledger/state files.",
    )
    args = parser.parse_args()
    date = args.date or _ny_today()
    print(f"Post-scan pipeline: date={date} dry_run={args.dry_run}", flush=True)
    try:
        run_pipeline(date, dry_run=args.dry_run)
    except SystemExit:
        # Mandatory step failure — already notified inside run_pipeline.
        raise
    except Exception as exc:
        _notify(
            "ERROR",
            "Post-scan pipeline CRASHED",
            f"date={date}\n{type(exc).__name__}: {exc}",
            dry_run=args.dry_run,
        )
        raise


if __name__ == "__main__":
    main()

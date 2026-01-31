#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo


@dataclass
class Check:
    check_id: str
    status: str  # PASS/WARN/FAIL
    detail: str


def _run(cmd: List[str], env: Dict[str, str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env, check=False)
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return proc.returncode, out.strip()


def _read_last_jsonl(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    last = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    if not last:
        return None
    return json.loads(last)


def main() -> int:
    checks: List[Check] = []

    repo_root = Path(os.environ.get("AVWAP_BASE_DIR", ".")).resolve()
    py = os.environ.get("AVWAP_PYTHON")
    if not py:
        venv_py = repo_root / "venv" / "bin" / "python"
        py = str(venv_py) if venv_py.exists() else sys.executable
    now_ny = datetime.now(tz=ZoneInfo("America/New_York"))
    ny_date = now_ny.date().isoformat()

    decision_path = repo_root / "ledger" / "PORTFOLIO_DECISIONS" / f"{ny_date}.jsonl"

    env = dict(os.environ)
    # Point Execution V2 at this working copy (prevents accidental /root writes on Mac).
    env["AVWAP_BASE_DIR"] = str(repo_root)
    env["AVWAP_STATE_DIR"] = str(repo_root / "state")
    # Provide deterministic S2 defaults for dev/local runs (droplet typically sets these via .env/systemd).
    env.setdefault("S2_SLEEVES_JSON", '{"sleeves":{"S1_AVWAP_CORE":{"max_daily_loss_usd":250.0,"max_gross_exposure_usd":5000.0,"max_concurrent_positions":5}}}')
    env.setdefault("S2_DAILY_PNL_JSON", '{"S1_AVWAP_CORE":0.0}')
    # Force DRY_RUN semantics regardless of execution_mode routing.
    env["TEST_MODE"] = env.get("TEST_MODE", "0")
    env["DRY_RUN"] = "1"
    env["EXECUTION_MODE"] = env.get("EXECUTION_MODE", "ALPACA_PAPER")

    cmd = [
        py,
        "-m",
        "execution_v2.execution_main",
        "--run-once",
        "--ignore-market-hours",
    ]

    code, out = _run(cmd, env=env)
    print(out)

    if code != 0:
        checks.append(Check("execution.run_once", "FAIL", f"nonzero_exit={code}"))
        _print_checks(checks)
        return 1
    checks.append(Check("execution.run_once", "PASS", "completed"))

    rec = _read_last_jsonl(decision_path)
    if rec is None:
        checks.append(Check("decision_record.present", "FAIL", f"missing_or_empty={decision_path}"))
        _print_checks(checks)
        return 1
    checks.append(Check("decision_record.present", "PASS", str(decision_path)))

    mode = rec.get("mode", {})
    exec_mode = mode.get("execution_mode")
    dry_forced = mode.get("dry_run_forced")

    if exec_mode != "DRY_RUN":
        checks.append(Check("mode.execution_mode", "FAIL", f"expected=DRY_RUN got={exec_mode!r}"))
    else:
        checks.append(Check("mode.execution_mode", "PASS", "DRY_RUN"))

    if dry_forced is not True:
        checks.append(Check("mode.dry_run_forced", "FAIL", f"expected=true got={dry_forced!r}"))
    else:
        checks.append(Check("mode.dry_run_forced", "PASS", "true"))

    actions = rec.get("actions", {})
    errs = actions.get("errors", [])
    if errs:
        checks.append(Check("actions.errors", "FAIL", f"count={len(errs)}"))
    else:
        checks.append(Check("actions.errors", "PASS", "empty"))

    build = rec.get("build", {})
    git_dirty = build.get("git_dirty")
    if git_dirty is True:
        checks.append(Check("build.git_dirty", "WARN", "true"))
    else:
        checks.append(Check("build.git_dirty", "PASS", f"{git_dirty!r}"))

    sleeves = rec.get("sleeves", {})
    sleeves_map = sleeves.get("sleeves", {})
    if not sleeves_map:
        checks.append(Check("sleeves.loaded", "FAIL", "no_sleeves_found"))
    else:
        checks.append(Check("sleeves.loaded", "PASS", f"count={len(sleeves_map)}"))

    intents = rec.get("intents", {})
    intent_count = intents.get("intent_count", 0)
    market_open = rec.get("gates", {}).get("market", {}).get("is_open", None)
    # Zero intents is expected on weekends/off-hours (stub MD / closed market),
    # but we still report it so operators understand what happened.
    if intent_count:
        checks.append(Check("intents.present", "PASS", f"intent_count={intent_count}"))
    else:
        # WARN only; not a preflight failure.
        checks.append(Check("intents.present", "WARN", f"intent_count=0 market_is_open={market_open!r}"))

    overall = "PASS"
    for c in checks:
        if c.status == "FAIL":
            overall = "FAIL"
            break
    if overall != "FAIL" and any(c.status == "WARN" for c in checks):
        overall = "WARN"

    _print_checks(checks, overall=overall)
    return 0 if overall == "PASS" else (2 if overall == "WARN" else 1)


def _print_checks(checks: List[Check], overall: str | None = None) -> None:
    if overall is None:
        overall = "PASS" if not any(c.status == "FAIL" for c in checks) else "FAIL"
    print("avwap_execution_v2_preflight=true")
    print(f"result={overall}")
    for c in checks:
        print(f"check.{c.check_id}.status={c.status}")
        print(f"check.{c.check_id}.detail={c.detail}")


if __name__ == "__main__":
    raise SystemExit(main())

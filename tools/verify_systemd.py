#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from zoneinfo import ZoneInfo


@dataclass
class CheckResult:
    check_id: str
    status: str
    detail: str


def run_cmd(args: List[str]) -> tuple[int, str, str]:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def systemctl_show(unit: str, prop: str) -> tuple[int, str, str]:
    return run_cmd(["systemctl", "show", unit, f"-p{prop}", "--value"])


def check_path_writable(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "FAIL", f"missing: {path}"
    if os.access(path, os.W_OK):
        return "PASS", f"writable: {path}"
    return "FAIL", f"not writable: {path}"


def check_watchlist_freshness(base_dir: Path) -> tuple[str, str]:
    watchlist = base_dir / "daily_candidates.csv"
    if not watchlist.exists():
        return "FAIL", f"missing: {watchlist}"
    stat = watchlist.stat()
    now_ny = datetime.now(tz=ZoneInfo("America/New_York")).date()
    file_date_ny = datetime.fromtimestamp(stat.st_mtime, tz=ZoneInfo("America/New_York")).date()
    if file_date_ny == now_ny:
        return "PASS", f"fresh: {watchlist} ({file_date_ny})"
    return "FAIL", f"stale: {watchlist} (file_date={file_date_ny} today={now_ny})"


def main() -> int:
    checks: List[CheckResult] = []

    systemctl_path = shutil.which("systemctl")
    if systemctl_path:
        checks.append(CheckResult("systemctl.available", "PASS", systemctl_path))
    else:
        checks.append(CheckResult("systemctl.available", "WARN", "systemctl not found"))

    base_dir = Path(os.environ.get("AVWAP_BASE_DIR", "/root/avwap_r3k_scanner"))

    if systemctl_path:
        code, out, err = systemctl_show("scan.timer", "LoadState")
        if code == 0 and out:
            status = "PASS" if out == "loaded" else "FAIL"
            checks.append(CheckResult("scan.timer.load_state", status, out))
        else:
            checks.append(CheckResult("scan.timer.load_state", "FAIL", err or "unable to read"))

        code, out, err = systemctl_show("scan.timer", "OnCalendar")
        if code == 0 and out:
            tz_ok = "America/New_York" in out
            checks.append(
                CheckResult(
                    "scan.timer.on_calendar",
                    "PASS" if tz_ok else "WARN",
                    out,
                )
            )
        else:
            checks.append(CheckResult("scan.timer.on_calendar", "FAIL", err or "unable to read"))

        code, out, err = systemctl_show("execution.service", "LoadState")
        if code == 0 and out:
            status = "PASS" if out == "loaded" else "FAIL"
            checks.append(CheckResult("execution.service.load_state", status, out))
        else:
            checks.append(CheckResult("execution.service.load_state", "FAIL", err or "unable to read"))

        code, out, err = systemctl_show("execution.service", "ExecStartPre")
        if code == 0 and out:
            gate_ok = "check_watchlist_today.sh" in out
            checks.append(
                CheckResult(
                    "execution.service.execstartpre",
                    "PASS" if gate_ok else "WARN",
                    out,
                )
            )
        else:
            checks.append(CheckResult("execution.service.execstartpre", "FAIL", err or "unable to read"))

        code, out, err = systemctl_show("execution.service", "Restart")
        if code == 0 and out:
            checks.append(CheckResult("execution.service.restart", "PASS", out))
        else:
            checks.append(CheckResult("execution.service.restart", "FAIL", err or "unable to read"))

        code, out, err = systemctl_show("execution.service", "RestartPreventExitStatus")
        if code == 0 and out:
            checks.append(CheckResult("execution.service.restart_prevent_exit_status", "PASS", out))
        else:
            checks.append(
                CheckResult(
                    "execution.service.restart_prevent_exit_status",
                    "WARN",
                    err or "empty",
                )
            )

        code, out, err = systemctl_show("execution.service", "RestartSec")
        if code == 0 and out:
            checks.append(CheckResult("execution.service.restart_sec", "PASS", out))
        else:
            checks.append(CheckResult("execution.service.restart_sec", "WARN", err or "empty"))

    dropin_dir = Path("/etc/systemd/system/execution.service.d")
    watchlist_dropin = dropin_dir / "10-watchlist-gate.conf"
    restart_dropin = dropin_dir / "20-restart-policy.conf"
    for path in (watchlist_dropin, restart_dropin):
        status = "PASS" if path.exists() else "FAIL"
        checks.append(CheckResult(f"dropin.{path.name}", status, str(path)))

    for rel in ("state", "ledger", "cache"):
        status, detail = check_path_writable(base_dir / rel)
        checks.append(CheckResult(f"path.writable.{rel}", status, detail))

    status, detail = check_path_writable(base_dir)
    checks.append(CheckResult("path.writable.base_dir", status, detail))

    try:
        status, detail = check_watchlist_freshness(base_dir)
        checks.append(CheckResult("watchlist.freshness", status, detail))
    except Exception as exc:
        checks.append(CheckResult("watchlist.freshness", "WARN", f"unable to check: {exc}"))

    kill_switch = Path(os.environ.get("AVWAP_STATE_DIR", str(base_dir / "state"))) / "KILL_SWITCH"
    if kill_switch.exists():
        checks.append(CheckResult("kill_switch.present", "WARN", f"present: {kill_switch}"))
    else:
        checks.append(CheckResult("kill_switch.present", "PASS", "not present"))

    overall = "PASS"
    for check in checks:
        if check.status == "FAIL":
            overall = "FAIL"
            break
    if overall != "FAIL" and any(check.status == "WARN" for check in checks):
        overall = "WARN"

    print("avwap_systemd_verify_sanity_check=true")
    print("note=not_a_safety_guarantee")
    print(f"result={overall}")
    for check in checks:
        print(f"check.{check.check_id}.status={check.status}")
        print(f"check.{check.check_id}.detail={check.detail}")

    if overall == "PASS":
        return 0
    if overall == "FAIL":
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())

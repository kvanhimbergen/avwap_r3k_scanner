# Deployment & Runtime Architecture (Systemd-Based)

## Overview

This project runs an automated trading and scanning system on an Ubuntu server using **systemd services and timers**.  
**tmux- and cron-based execution is deprecated** and must not be used in production.

The system is designed to be:
- DST-safe (Eastern Time schedules)
- Idempotent and restart-safe
- Protected against trading with stale scan data
- Operated entirely through systemd

---

## Authoritative Runtime Components

### Long-Running Services

| Service | Purpose |
|------|------|
| `execution.service` | Execution V2 order and position execution loop |

Execution runs under systemd, restarts automatically on failure, and logs to `journald`.

---

### Scheduled Jobs (systemd timers)

| Timer | Schedule (ET) | Purpose |
|------|------|------|
| `scan.timer` | Mon–Fri **08:30 AM ET** | Runs daily market scan |
| `execution-restart.timer` | Mon–Fri **08:40 AM ET** | Restarts execution after scan |

> Timers are DST-safe using `OnCalendar=… America/New_York`.

---

## Execution Safety Guardrails

### Watchlist Gate (Critical)

Execution is **blocked from starting** unless:

- `daily_candidates.csv` exists
- File date (America/New_York) matches **today**

This is enforced by:

```ini
ExecStartPre=/root/avwap_r3k_scanner/bin/check_watchlist_today.sh
If the scan fails or the watchlist is stale:

Execution will not start

Restart storms are prevented by systemd policy

Deployment: The Only Approved Method
⚠️ IMPORTANT
Do NOT run deploy.sh in production.
It is tmux-based and will create duplicate processes.

✅ Approved Script
Use only:

bash
Copy code
sudo ./deploy_systemd.sh
What deploy_systemd.sh Does
Pulls latest code from main

Updates Python dependencies

Runs compile checks

Verifies universe cache presence

Verifies the watchlist gate script exists

Reloads systemd

Restarts:

execution.service

Verifies active timers

It never:

Starts tmux

Launches Python directly

Touches cron

Creates background processes

Typical Deployment Workflow
bash
Copy code
cd /root/avwap_r3k_scanner
sudo ./deploy_systemd.sh
Verify after deploy:

bash
Copy code
systemctl status execution.service --no-pager
systemctl list-timers --all | grep -E 'scan\.timer|execution-restart\.timer'
Logs & Monitoring
All logs are in journald.

Examples:

bash
Copy code
journalctl -u execution.service --since "today" --no-pager
journalctl -u scan.service --since "today" --no-pager
Process Verification (Sanity Check)
At any time, this should show exactly one execution process:

bash
Copy code
pgrep -af "execution_v2/execution_main.py"
And no tmux sessions:

bash
Copy code
tmux ls
Common Failure Modes (and What to Do)
Execution will not start
Check:

bash
Copy code
journalctl -u execution.service -n 50 --no-pager
Likely cause: missing or stale daily_candidates.csv

Fix: ensure scan.service ran successfully

Scan did not run
Check:

bash
Copy code
systemctl status scan.timer scan.service --no-pager
Confirm timer schedule:

bash
Copy code
systemd-analyze calendar "Mon..Fri 08:30 America/New_York"
Do Not Do These Things
❌ Run deploy.sh
❌ Start execution_v2/execution_main.py manually
❌ Use tmux in production
❌ Add cron jobs
❌ Modify systemd unit files without documenting changes


Checks for readiness:
systemctl list-timers --all | grep -E 'scan\.timer|execution-restart\.timer'
systemctl status execution.service --no-pager

One-Command Morning Health Check
avwap-check

What “good” looks like

execution.service → active

scan.timer shows next run at 08:30 America/New_York

execution-restart.timer shows next run at 08:40 America/New_York

Watchlist check prints OK: Watchlist is fresh for today (NY)

Exactly one execution process (execution_v2)


Files of Interest
Path	Purpose
deploy_systemd.sh	Authoritative deploy script
bin/check_watchlist_today.sh	Execution safety gate
execution_v2/execution_main.py	Execution V2 entrypoint
/etc/systemd/system/*.service	Runtime services
/etc/systemd/system/*.timer	Schedules

Architectural Principle
systemd is the single source of truth for process lifecycle and scheduling.

Any deviation from this model risks duplicate execution, stale trades, or undefined behavior.

Last Updated
2026-01-15

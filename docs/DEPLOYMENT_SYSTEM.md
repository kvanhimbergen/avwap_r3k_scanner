# Deployment & Runtime Architecture (Systemd-Based)

## Overview

This project runs an automated trading and scanning system on an Ubuntu server using **systemd services and timers**.  
**tmux- and cron-based execution is deprecated** and must not be used in production.

The system is designed to be:
- DST-safe (Eastern Time schedules)
- Idempotent and restart-safe
- Protected against trading with stale scan data
- Operated entirely through systemd

**Systemd verification runbook:** see [`docs/RUNBOOK_SYSTEMD_VERIFY.md`](RUNBOOK_SYSTEMD_VERIFY.md) for the deterministic verification sweep.
**Analytics platform runbook:** see [`docs/RUNBOOK_ANALYTICS_PLATFORM.md`](RUNBOOK_ANALYTICS_PLATFORM.md) for service/tunnel/health verification.

---

## Authoritative Runtime Components

### Long-Running Services

| Service | Purpose |
|------|------|
| `execution.service` | Execution V2 order and position execution loop |
| `analytics-platform.service` | Read-only analytics API for AVWAP/S2 monitoring (`127.0.0.1:8787`) |

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

### Deployment Assumptions (Important)

The current system assumes:

- The codebase lives at /root/avwap_r3k_scanner
- The execution user has write access to the repository directory

The following paths must be writable at runtime:
- daily_candidates.csv
- tradingview_watchlist.txt
- cache/ (including bad_tickers.txt)
- state/ (dry-run ledger, kill switch)
- ledger/ (execution, attribution, caps)
- data/execution_v2.sqlite

Non-root or read-only deployments are currently out of scope unless
paths are reconfigured via environment variables.


### Fail-Closed vs Fail-Open Enforcement Model

This system intentionally splits safety enforcement across two layers:

Fail-closed (hard stop, enforced by systemd):
- Watchlist freshness gate (`ExecStartPre` via check_watchlist_today.sh)
- Restart storm prevention (systemd RestartPreventExitStatus drop-ins)
- Live trading gate (LIVE_TRADING + confirm token)
- Alpaca clock / market status failures

Fail-open (runtime, execution continues with warnings):
- Market regime checks
- Earnings proximity checks
- Optional analytics / attribution modules
- Dry-run ledger write failures

Important: Not all safety guarantees are enforced in Python. Several critical gates live exclusively in systemd and are only active if the correct unit files and drop-ins are installed.


### Timezone Semantics (Important)

Execution components (Execution V2, live gates, market-hours enforcement, and drawdown guards) operate strictly in `America/New_York` time and rely on exchange-aligned clocks for determinism.

The scan pipeline and cache freshness logic currently use the **local system timezone** for:
- weekend detection
- cache TTL and freshness checks

This is intentional but means scan behavior may differ around DST boundaries or if the host timezone is not aligned with New York.

Operators should ensure system timezone consistency or account for this when validating deterministic scan output.

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
⚠️ IMPORTANT: systemd drop-ins are required

Restart-storm prevention and the watchlist freshness gate are enforced via
systemd drop-in files (e.g. execution.service.d/).

These are NOT installed by deploy_systemd.sh.

You must run the following at least once on a new host:

sudo ./ops/install_systemd_units.sh

If this step is skipped, execution may start without the watchlist gate
and restart-storm protection will not be active.


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

Execution V2 State Artifacts
Execution V2 writes lightweight artifacts under `state/` and `ledger/` to support
observability and deterministic audits:

- `state/execution_heartbeat.json` is written every non-fatal cycle (including market-closed cycles).
  It captures the current execution mode, market-open status, and lightweight intent/error counts.
- `state/portfolio_decision_latest.json` and `ledger/PORTFOLIO_DECISIONS/<date>.jsonl` are now
  **material-only** artifacts. They only update when the cycle is material (market open, intents,
  orders, or errors). Market-closed "no-op" cycles intentionally do **not** update these files.
- `state/symbol_execution_state_<NYDATE>.json` captures per-symbol execution lifecycle state
  (FLAT/ENTERING/OPEN/EXITING) for restart-safe gating.
- `state/consumed_entries_<NYDATE>.json` records one-entry-per-symbol-per-day consumption.

ALPACA_PAPER credential checks are fail-closed: missing `APCA_API_KEY_ID`,
`APCA_API_SECRET_KEY`, or `APCA_API_BASE_URL` will raise an error and skip all artifact writes.

### Execution DB Path (Pin + Verify)

Execution V2 reads/writes state from `--db-path`, which defaults to:

- `EXECUTION_V2_DB` (if set), otherwise
- `data/execution_v2.sqlite` (resolved from `execution.service` `WorkingDirectory`)

Recommended production pin (systemd drop-in):

```ini
[Service]
Environment=EXECUTION_V2_DB=/root/avwap_r3k_scanner/data/execution_v2.sqlite
```

Verification commands:

```bash
systemctl show execution.service -p WorkingDirectory -p Environment
journalctl -u execution.service -n 100 --no-pager | grep "Execution DB:"
grep -n "\"db_path\\|db_path_abs\\|db_exists\\|db_mtime_utc\\|db_size_bytes\"" /root/avwap_r3k_scanner/state/portfolio_decision_latest.json
```

`state/portfolio_decision_latest.json` now records these DB metadata fields under `inputs`
for each cycle so DB-path mismatches are immediately visible.

### Execution Tuning Knobs

Execution polling and entry throttles are deterministic and configurable via environment variables:

- `EXECUTION_POLL_SECONDS` (base poll interval)
- `EXECUTION_POLL_TIGHT_SECONDS` (default: `15`)
- `ENTRY_DELAY_AFTER_OPEN_MINUTES` (default: `20`, entry orders blocked until after open + delay)
- `MIN_EXIT_ARMING_SECONDS` (default: `120`, exit orders blocked until after entry fill delay)
- `EXECUTION_POLL_TIGHT_START_ET` (default: `09:30`)
- `EXECUTION_POLL_TIGHT_END_ET` (default: `10:05`)
- `EXECUTION_POLL_MARKET_SECONDS` (default: `min(EXECUTION_POLL_SECONDS, 60)`)

During market hours, polling uses the tight window first, otherwise the market window.
Outside market hours it falls back to the base poll interval. Invalid values fall back
to defaults with a single warning at startup.

Optional settle gate:

- `MARKET_SETTLE_MINUTES` (default: `0`, disabled)

When enabled, new entry creation/submission is blocked for the first N minutes after
the open, while exits and position management continue to run.
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

Offline config sanity check (no network):

```bash
python execution_v2/execution_main.py --config-check
```

> **Scope Note**
>
> `--config-check` validates **execution configuration only** (environment variables, required paths, and basic runtime wiring).

### What to do
Immediately **after that code block**, add a clarification paragraph.

### What to add
```markdown
> **Scope Note**
>
> `--config-check` validates **execution configuration only** (environment variables, required paths, and basic runtime wiring).
>
> It does **not** validate:
> - scan freshness
> - watchlist age
> - universe completeness
> - market regime availability
>
> Passing `--config-check` indicates the execution environment is internally consistent, not that it is safe or optimal to trade.


One-Command Morning Health Check
Use the offline, deterministic preflight validator:

```bash
python -m tools.avwap_check --mode all
```

Notes:
- Offline-only: no network calls and no order placement.
- Exit codes: `0=PASS`, `1=FAIL`, `2=WARN` (unless `--strict`, which turns WARN into FAIL).
- WARN means safe to proceed but review output; FAIL means address issues before running.
- This is a preflight validator, not a trading safety guarantee.

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

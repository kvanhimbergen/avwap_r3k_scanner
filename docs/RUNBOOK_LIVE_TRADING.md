# Live Trading Runbook (Solo Operator)

## 1) Purpose & Scope
- **Default mode is DRY_RUN.** Live orders are **OFF** unless explicitly enabled by the two-key gate. This is a safety-first runbook for enabling LIVE intentionally.
- **No strategy changes are in scope.** This runbook only covers operating the existing execution pipeline safely.
- **No systemd units are committed to git.** All systemd changes are deployment-only and should remain local.

**Operational clarification (important):**
- All systemd configuration changes must be made using **drop-in files** on the droplet only.
- Use: `/etc/systemd/system/execution.service.d/*.conf`
- Do **not** copy systemd unit files or drop-ins into this repository.
- Before committing any changes, run `git status` and confirm **no systemd files appear**.


## 2) Safety Model Summary (plain English)
- **Fail-closed:** If anything is missing or inconsistent (token mismatch, ledger missing, positions unknown, etc.), the system **falls back to DRY_RUN** automatically.
- **Two-key confirmation:** LIVE requires **both** `LIVE_TRADING=1` **and** a matching `LIVE_CONFIRM_TOKEN` that **exactly matches** the file contents in the state directory.
- **Caps + allowlist:** Even when LIVE is enabled, orders are blocked if they exceed daily caps (orders/positions/notional) or are not on the allowlist (if configured).
- **Kill switch:** Setting `KILL_SWITCH=1` or creating the `KILL_SWITCH` file **immediately disables LIVE** and forces DRY_RUN behavior.

## 3) Preconditions / Pre-LIVE Checklist
**Must be true before enabling LIVE:**
- [ ] **DRY_RUN has run cleanly for several days** (no errors, no unexpected skips).
- [ ] **Scan artifacts are fresh** (daily candidates & watchlist updated today).
- [ ] **Slack alerts are healthy** (heartbeat and daily summary visible).
- [ ] **Broker credentials configured** (APCA_API_KEY_ID / APCA_API_SECRET_KEY present on the host).
- [ ] **System time/timezone are correct** (host clock aligned; logs show ET timestamps).
- [ ] **execution.service is running** and **DRY_RUN is enforced** via a systemd drop-in or environment.

**Safe inspection commands (examples):**
- `systemctl status execution.service`
- `journalctl -u execution.service -n 200 --no-pager`
- `date`

## 3.5) Go / No-Go Gate Before Enabling LIVE (Hard Requirement)

**Do NOT enable LIVE unless all of the following are true in the same session/day:**

- [ ] Watchlist freshness gate is passing (no preflight failures).
- [ ] Execution service is running and stable in DRY_RUN.
- [ ] Slack heartbeat and daily summary are visible.
- [ ] Logs show explicit gate output in DRY_RUN:
  - `Gate mode=DRY_RUN status=FAIL reason=...`
- [ ] Day-1 caps and (if used) allowlist are explicitly set and conservative.
- [ ] You understand how to immediately trigger the kill switch.

**LIVE enablement is a deliberate operator decision.**  
If any item above is not satisfied, do **not** proceed.

## 4) Live Enablement Procedure (Step-by-step, exact commands)
> **Important:** Do not remove DRY_RUN enforcement until the two-key confirmation is in place.

### 4.1 Generate a confirm token file (safe)
```bash
STATE_DIR="${AVWAP_STATE_DIR:-/root/avwap_r3k_scanner/state}"
mkdir -p "${STATE_DIR}"
TOKEN="$(openssl rand -hex 16)"
printf "%s" "${TOKEN}" > "${STATE_DIR}/live_confirm_token.txt"
chmod 600 "${STATE_DIR}/live_confirm_token.txt"
```

### 4.2 Configure environment variables (operator action guidance)
Set **both** of the following in the systemd drop-in or service environment (do **not** commit changes to git):
```bash
LIVE_TRADING=1
LIVE_CONFIRM_TOKEN=<paste token from live_confirm_token.txt>
```

Optional safety-first settings for day 1 (recommended):
```bash
ALLOWLIST_SYMBOLS=SYM1,SYM2
MAX_LIVE_ORDERS_PER_DAY=1
MAX_LIVE_POSITIONS=1
MAX_LIVE_GROSS_NOTIONAL=500
MAX_LIVE_NOTIONAL_PER_SYMBOL=250
```

### 4.3 Ensure DRY_RUN is removed only after two-key is set
- Confirm the drop-in (or environment source) includes `LIVE_TRADING=1` and `LIVE_CONFIRM_TOKEN`.
- **Then** remove/override `DRY_RUN=1` in the same place.
- Reload and restart the service:
```bash
systemctl daemon-reload
systemctl restart execution.service
```

### 4.4 Live ledger requirement
The live ledger must exist at:
```
${STATE_DIR}/live_orders_today.json
```
**Behavior:** If the ledger is missing or unreadable, LIVE is **blocked for that cycle** and the system remains in DRY_RUN. This is fail-closed.

### 4.5 Enable LIVE for a Single Day (Recommended First Deployment)

This procedure allows controlled exposure for one session/day.

**Enable (pre-market):**
- Set `LIVE_TRADING=1` and `LIVE_CONFIRM_TOKEN` in the systemd drop-in.
- Ensure caps and allowlist are conservative.
- Remove or override `DRY_RUN=1`.
- Restart the service and confirm logs show:
  - `Gate mode=LIVE status=PASS ...`

**Disable (after market close):**
- Re-enable `DRY_RUN=1` in the same systemd drop-in.
- Optionally remove `LIVE_TRADING=1`.
- Restart the service.
- Confirm logs show:
  - `Gate mode=DRY_RUN status=FAIL reason=DRY_RUN enabled`

**Rule:** LIVE should never be left enabled overnight unintentionally.

## 5) Verification Checklist (prove LIVE is enabled)

**Important timing note:**  
Gate status lines (`Gate mode=...`, allowlist, caps) are emitted **only when the execution loop reaches the market-hours evaluation path**.  
If the market is closed (and `--ignore-market-hours` is not set), execution returns early after logging:

```
Market closed; skipping cycle.
```

In that case, gate lines will **not** appear in logs until the market is open.

**Journalctl log lines to confirm:**
- `Gate mode=LIVE status=PASS reason=live trading confirmed`
- `Gate allowlist=ALL` **or** `Gate allowlist=SYM1,SYM2`
- `Gate caps(orders/day=..., positions=..., gross_notional=..., per_symbol=...)`

**Slack expectations:**
- One-time Slack alert: **“Live trading enabled”** (throttled).

**Unambiguous confirmation of LIVE vs DRY_RUN:**
- LIVE: `Gate mode=LIVE status=PASS ...`
- DRY_RUN: `Gate mode=DRY_RUN status=FAIL reason=...`

## 6) Normal Daily Ops Workflow (Solo Operator)
### Morning checklist (pre-market)
- [ ] Confirm today’s scan artifacts exist and are fresh.
- [ ] Verify `execution` is running.
- [ ] Check Slack heartbeat and daily summary.
- [ ] Review yesterday’s live ledger (if LIVE was enabled).

### During market hours
- [ ] Watch `journalctl` for gate lines and any `ERROR` or `WARNING` messages.
- [ ] If LIVE, confirm allowlist and caps are printed as expected.
- [ ] Confirm no unexpected repeated submissions. Same-day duplicates are prevented per symbol in the DRY_RUN ledger (best-effort); duplicates across days may occur. Operator should monitor logs and validate the ledger.

### After close
- [ ] Review the live ledger file for recorded orders.
- [ ] Confirm daily summary Slack message is received.
- [ ] If any anomalies, proceed to Emergency Procedures and record findings.

### How to interpret daily summaries / ledgers
- **Live ledger** records each LIVE order with timestamp, symbol, and notional.
- **DRY_RUN** orders are not placed live but still log `SUBMITTED` with `order_id=dry-run`.

## 7) Emergency Procedures (No thinking required)
### Immediate disable via env kill switch
```bash
# In systemd drop-in or service env
KILL_SWITCH=1
systemctl daemon-reload
systemctl restart execution.service
```

### Immediate disable via state file kill switch
```bash
STATE_DIR="${AVWAP_STATE_DIR:-/root/avwap_r3k_scanner/state}"
touch "${STATE_DIR}/KILL_SWITCH"
```

### Fallback: force DRY_RUN
```bash
# In systemd drop-in or service env
DRY_RUN=1
systemctl daemon-reload
systemctl restart execution.service
```

### Confirm shutdown state
- Logs should show: `Gate mode=DRY_RUN status=FAIL reason=kill switch active (...)` or `reason=DRY_RUN enabled`.
- Slack should show **“Kill switch active”** once (throttled).

### Broker-side emergency steps (high-level)
- Cancel open orders immediately.
- Close positions if needed.
- Disable API keys if necessary.

## 8) Failure Modes & Expected System Behavior
- **Stale watchlist:** execution won’t start (watchlist gate enforces freshness).
- **Alpaca clock errors:** market assumed closed; execution skips cycle.
- **Live token mismatch:** system stays in DRY_RUN.
- **Live ledger missing or unreadable:** LIVE is blocked for that cycle and the system remains in DRY_RUN (fail-closed).
- **Slack failures:** trading continues; operator should treat as degraded observability.

## 9) Post-Incident Recovery Checklist
- [ ] Clear kill switch (env and/or file).
- [ ] Regenerate confirm token if necessary; update `LIVE_CONFIRM_TOKEN`.
- [ ] Validate caps and allowlist are conservative.
- [ ] Restart execution service safely.
- [ ] Confirm no duplicate orders and ledger integrity.

## 10) Appendix
### Env vars (defaults and behavior)
- `DRY_RUN=1` → forces DRY_RUN regardless of other settings.
- `LIVE_TRADING=1` → **required** for LIVE.
- `LIVE_CONFIRM_TOKEN` → **required** and must match file.
- `KILL_SWITCH=1` → disables LIVE immediately.
- `AVWAP_STATE_DIR` → overrides state dir (default: `/root/avwap_r3k_scanner/state`).
- `ALLOWLIST_SYMBOLS` → comma-separated; empty allows all.
- `MAX_LIVE_ORDERS_PER_DAY` (default **5**)
- `MAX_LIVE_POSITIONS` (default **5**)
- `MAX_LIVE_GROSS_NOTIONAL` (default **5000.0**)
- `MAX_LIVE_NOTIONAL_PER_SYMBOL` (default **1000.0**)

### File paths (Phase 6)
- State dir: `/root/avwap_r3k_scanner/state` (override via `AVWAP_STATE_DIR`)
- Kill switch file: `${STATE_DIR}/KILL_SWITCH`
- Confirm token file: `${STATE_DIR}/live_confirm_token.txt`
- Live ledger: `${STATE_DIR}/live_orders_today.json`

### Safe inspection commands
- `systemctl status execution.service`
- `systemctl cat execution.service`
- `systemctl cat execution.service.d/override.conf`
- `journalctl -u execution.service -n 200 --no-pager`
- `journalctl -u execution.service --since "today" --no-pager`
- `cat ${STATE_DIR}/live_confirm_token.txt`
- `cat ${STATE_DIR}/live_orders_today.json`

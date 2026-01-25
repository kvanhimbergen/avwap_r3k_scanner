# Systemd Runbook Verification Sweep

This runbook provides a deterministic, operator-friendly verification sweep to confirm **systemd guardrails** are installed and working as documented.

> **Scope**
>
> This runbook is **verification-only**. It does not modify systemd units or execution logic. All commands are offline-only.

## Prereqs

- Host is an Ubuntu server using **systemd** as PID 1.
- Repository is located at: `/root/avwap_r3k_scanner`.
- Python virtual environment lives at `/root/avwap_r3k_scanner/.venv` (or your standard venv path for this deployment).
- You have sudo access for systemd inspection commands.
- You understand the kill switch behavior and can safely test it **outside market hours** or with `DRY_RUN=1`.

## Step-by-step checklist (one command per step)

### 1) Confirm repo path exists
**Command**
```bash
test -d /root/avwap_r3k_scanner
```
**Expected**
- Exit code `0`.

**If not expected then…**
- Fix the repository path and ensure deployment matches the documented location.

---

### 2) Confirm Python venv exists
**Command**
```bash
test -d /root/avwap_r3k_scanner/.venv
```
**Expected**
- Exit code `0`.

**If not expected then…**
- Create or restore the venv per your deployment standard before proceeding.

---

### 3) Confirm `scan.timer` is installed
**Command**
```bash
systemctl show scan.timer -p LoadState --value
```
**Expected**
- Output: `loaded`.

**If not expected then…**
- Reinstall systemd units: `sudo ./ops/install_systemd_units.sh`.

---

### 4) Verify `scan.timer` schedule and timezone
**Command**
```bash
systemctl show scan.timer -p TimersCalendar --value
```
**Expected**
- Output includes: `Mon..Fri 08:30 America/New_York`.

**If not expected then…**
- Reinstall systemd units and verify you are running the canonical unit files from `ops/systemd/`.

---

### 5) Confirm host timezone (for sanity)
**Command**
```bash
timedatectl show -p Timezone --value
```
**Expected**
- Output typically `America/New_York` (or your explicit deployment timezone).

**If not expected then…**
- Align the host timezone to match deployment expectations or explicitly account for the mismatch when validating scan behavior.

---

### 6) Confirm `execution.service` is installed
**Command**
```bash
systemctl show execution.service -p LoadState --value
```
**Expected**
- Output: `loaded`.

**If not expected then…**
- Reinstall systemd units: `sudo ./ops/install_systemd_units.sh`.

---

### 7) Confirm watchlist freshness gate is wired (ExecStartPre)
**Command**
```bash
systemctl show execution.service -p ExecStartPre --value
```
**Expected**
- Output includes: `bin/check_watchlist_today.sh`.

**If not expected then…**
- Verify you installed drop-ins and reload systemd: `sudo ./ops/install_systemd_units.sh && sudo systemctl daemon-reload`.

---

### 8) Confirm execution drop-ins are installed (watchlist gate + restart policy)
**Command**
```bash
ls -1 /etc/systemd/system/execution.service.d/10-watchlist-gate.conf /etc/systemd/system/execution.service.d/20-restart-policy.conf
```
**Expected**
- Both files listed without errors.

**If not expected then…**
- Install drop-ins: `sudo ./ops/install_systemd_units.sh`.

---

### 9) Verify restart semantics are present
**Command**
```bash
systemctl show execution.service -p Restart -p RestartPreventExitStatus -p RestartSec
```
**Expected**
- `Restart=...` is set (usually `on-failure`).
- `RestartPreventExitStatus=...` is non-empty.
- `RestartSec=...` is non-empty.

**If not expected then…**
- Reinstall systemd units and drop-ins; ensure `20-restart-policy.conf` is present.

---

### 10) Verify writable paths required by runtime
**Command**
```bash
for p in /root/avwap_r3k_scanner/state /root/avwap_r3k_scanner/ledger /root/avwap_r3k_scanner/cache /root/avwap_r3k_scanner; do test -w "$p"; done
```
**Expected**
- Exit code `0`.

**If not expected then…**
- Fix permissions/ownership for the execution user.
- Ensure the repo is not mounted read-only.

---

### 11) Verify daily watchlist freshness (live file)
**Command**
```bash
/root/avwap_r3k_scanner/bin/check_watchlist_today.sh
```
**Expected**
- Output: `OK: Watchlist is fresh for today (NY): ...`.

**If not expected then…**
- Re-run scan via `systemctl start scan.service`.
- Confirm the scan output wrote `daily_candidates.csv` for today (NY).

---

### 12) Prove watchlist gate blocks a stale file (safe dry-run test)
**Command**
```bash
sudo bash -lc 'f=/root/avwap_r3k_scanner/daily_candidates.csv.stale_test && install -m 0644 /dev/null "$f" && touch -d "yesterday" "$f" && WATCHLIST_FILE="$(basename "$f")" /root/avwap_r3k_scanner/bin/check_watchlist_today.sh; rc=$?; rm -f "$f"; exit $rc'
```
**Expected**
- Command exits **non-zero**.
- Output includes: `Watchlist is not from today (NY)`.

**If not expected then…**
- The gate script is not behaving as expected; verify `bin/check_watchlist_today.sh` matches the deployed version.

---

### 13) Verify kill switch behavior (no trades)
**Command**
```bash
sudo bash -lc 'STATE_DIR="${AVWAP_STATE_DIR:-/root/avwap_r3k_scanner/state}"; touch "${STATE_DIR}/KILL_SWITCH"; systemctl restart execution.service'
```
**Expected**
- `execution.service` restarts without placing trades.

**If not expected then…**
- Stop the service and investigate logs (see step 14).
- Confirm this test is run **outside market hours** or with `DRY_RUN=1`.

---

### 14) Confirm kill switch is acknowledged in logs
**Command**
```bash
journalctl -u execution.service -n 100 --no-pager | rg -n "kill switch active|Gate mode=DRY_RUN"
```
**Expected**
- A log line indicating kill switch active or DRY_RUN enforcement.

**If not expected then…**
- Re-check step 13; ensure the kill switch file exists and the service restarted.

---

### 15) Clear the kill switch after verification
**Command**
```bash
sudo bash -lc 'STATE_DIR="${AVWAP_STATE_DIR:-/root/avwap_r3k_scanner/state}"; rm -f "${STATE_DIR}/KILL_SWITCH"; systemctl restart execution.service'
```
**Expected**
- Service restarts normally.

**If not expected then…**
- Stop the service and verify file permissions and path overrides.

---

### 16) Verify `scan.timer` and `execution-restart.timer` scheduling
**Command**
```bash
systemctl list-timers --all | rg -n "scan\.timer|execution-restart\.timer"
```
**Expected**
- `scan.timer` next run is 08:30 America/New_York.
- `execution-restart.timer` next run is 08:40 America/New_York.

**If not expected then…**
- Confirm unit files match `ops/systemd/` and reload systemd.

---

### 17) Optional: run the offline verification script
**Command**
```bash
python /root/avwap_r3k_scanner/tools/verify_systemd.py
```
**Expected**
- Exit code `0` for PASS.
- Exit code `2` if WARN conditions are detected.

**If not expected then…**
- Review the printed report and resolve FAIL items.

---

## Journalctl troubleshooting snippets

- Execution logs (today):
  ```bash
  journalctl -u execution.service --since "today" --no-pager
  ```
- Scan logs (today):
  ```bash
  journalctl -u scan.service --since "today" --no-pager
  ```
- Timer diagnostics:
  ```bash
  systemctl status scan.timer execution-restart.timer --no-pager
  ```

## Notes

- This sweep is **offline-only** and does not perform network calls.
- It is a sanity check of systemd wiring, not a trading safety guarantee.

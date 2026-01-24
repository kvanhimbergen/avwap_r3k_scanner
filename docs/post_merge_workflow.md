Post-Merge Workflow

Updating Local MacBook + DigitalOcean Droplet After Codex PRs

This document defines the standard operating procedure (SOP) to follow after merging one or more Codex-generated pull requests into main.

The goals are:

keep local and droplet environments in sync

verify nothing broke before production runs

preserve determinism and reproducibility

avoid universe / network-related failures

0. Pre-flight assumptions

Canonical branch: main

Repo cloned on:

Local MacBook (development)

DigitalOcean droplet (production scan/backtest)

Python virtual environment exists on both (venv/)

Universe snapshot workflow is in place (universe/cache/iwv_holdings.csv)

Codex PRs have already been merged into GitHub → main

1. Update local MacBook (first, always)
1.1 Navigate to repo
cd ~/avwap_r3k_scanner

1.2 Ensure clean working tree
git status


If dirty: either commit or stash changes before proceeding.

1.3 Pull latest main
git fetch origin
git checkout main
git pull --ff-only origin main

1.4 Verify commit hash
git log -1 --oneline


Keep this commit hash handy — it should later match the droplet.

2. Refresh Python environment (local)
2.1 Activate venv
source venv/bin/activate

2.2 Install/update dependencies (safe to re-run)
pip install -r requirements-dev.txt

3. Run local safety checks (MANDATORY)
3.1 Run minimal test harness
python tests/run_tests.py


Expected output:

test_no_network: PASS
test_no_lookahead: PASS
test_determinism: PASS

ALL TESTS PASSED


❌ Do not proceed if any test fails.

4. Refresh universe snapshot (local MacBook)

This step should be run from a non-blocked IP (your MacBook).

4.1 Refresh IWV universe snapshot
python tools/refresh_iwv_holdings.py


Expected output:

Row count

Unique tickers

Timestamp

4.2 Commit snapshot if it changed
git status
git add universe/cache/iwv_holdings.csv
git commit -m "Update IWV universe snapshot"
git push origin main


If unchanged, no commit is required.

5. Update DigitalOcean droplet
5.1 SSH into droplet
ssh root@<droplet-ip>

5.2 Navigate to repo
cd /root/avwap_r3k_scanner

5.3 Stop running services (scan / execution)
sudo systemctl stop scan.service || true
sudo systemctl stop execution.service || true


(Exact service names may differ — stop all scanner/execution units.)

6. Sync droplet code with GitHub
6.1 Pull latest main
git fetch origin
git checkout main
git pull --ff-only origin main

6.2 Verify commit hash
git log -1 --oneline


Confirm this matches the MacBook commit hash.

7. Refresh droplet Python environment
7.1 Activate venv
source venv/bin/activate

7.2 Install/update dependencies
pip install -r requirements-dev.txt

8. Verify universe snapshot presence (CRITICAL)
8.1 Confirm snapshot exists
ls -lh universe/cache/iwv_holdings.csv


If missing:

Copy from local MacBook or

Pull again from GitHub if committed

⚠️ The droplet must not attempt to download IWV live.

9. Run droplet safety checks
9.1 Run test harness on droplet
python tests/run_tests.py


Expected:

ALL TESTS PASSED

9.2 Dry-run scan (no orders)
python run_scan.py


Confirm:

daily_candidates.csv generated

No network / IWV errors

Output schema unchanged

10. Backtest sanity check (optional but recommended)
python run_backtest.py \
  --mode historical_scan \
  --start 2023-01-01 \
  --end 2023-03-31


Verify:

historical_candidates.parquet created

backtest_run_manifest.json created

No lookahead or network warnings

11. Restart production services
sudo systemctl start scan.service
sudo systemctl start execution.service

11.1 Confirm status
sudo systemctl status scan.service --no-pager
sudo systemctl status execution.service --no-pager

12. Post-deploy verification checklist

Confirm the following:

 Local and droplet commit hashes match

 Tests passed on both environments

 Universe snapshot present on droplet

 Scan runs without network calls

 No schema changes to scan outputs

 Services restarted cleanly

13. Failure recovery (quick reference)
If scan fails on droplet:

Stop services

Re-run python run_scan.py manually

Inspect stack trace

Check:

universe snapshot exists

config flags (network disabled in backtest)

environment variables

If universe download fails:

Never debug on droplet

Refresh snapshot on MacBook

Commit or copy snapshot

Redeploy

14. Guiding principles (for future you)

MacBook = networked, refresh artifacts

Droplet = offline, deterministic

Backtests never hit the network

Scans and backtests share one engine

Every merge = tests + snapshot check
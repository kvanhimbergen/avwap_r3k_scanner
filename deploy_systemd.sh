#!/bin/bash
set -euo pipefail

PROJECT_DIR="/root/avwap_r3k_scanner"
VENV_PATH="$PROJECT_DIR/venv"
BRANCH="main"

echo "Starting deployment (SYSTEMD MODE)..."

cd "$PROJECT_DIR"

echo "Pulling latest code from $BRANCH..."
git checkout "$BRANCH" >/dev/null 2>&1 || true
git pull origin "$BRANCH"

echo "Updating Python libraries..."
source "$VENV_PATH/bin/activate"
pip install -r requirements.txt

echo "Running Python compile checks..."
python -m py_compile \
  universe.py \
  run_scan.py \
  ops/post_scan_pipeline.py \
  analytics_platform/backend/main.py \
  analytics_platform/backend/app.py \
  execution_v2/execution_main.py \
  execution_v2/alpaca_s2_bracket_adapter.py \
  strategies/s2_letf_orb_alpaca.py \
  strategies/raec_401k_v2.py \
  config.py

echo "Ensuring cache directory exists..."
mkdir -p "$PROJECT_DIR/cache"
if [ -f "$PROJECT_DIR/cache/iwv_holdings.csv" ]; then
  echo "Universe cache present: cache/iwv_holdings.csv"
else
  echo "WARNING: Universe cache missing."
  echo "This droplet cannot fetch iShares; seed via scp from your Mac."
fi

# Gate script required by execution.service ExecStartPre
if [ ! -x "$PROJECT_DIR/bin/check_watchlist_today.sh" ]; then
  echo "ERROR: Missing gate script: $PROJECT_DIR/bin/check_watchlist_today.sh"
  exit 1
fi

echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Restarting services (systemd-managed)..."
sudo systemctl restart execution.service
sudo systemctl restart analytics-platform.service || true

echo "Verifying timers..."
sudo systemctl restart scan.timer execution-restart.timer post-scan.timer >/dev/null 2>&1 || true
systemctl list-timers --all | grep -E 'scan\.timer|execution-restart\.timer|post-scan\.timer|NEXT|LEFT' || true

echo "Deployment complete (SYSTEMD MODE)."

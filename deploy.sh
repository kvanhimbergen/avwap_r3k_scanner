#!/bin/bash
set -euo pipefail

PROJECT_DIR="/root/avwap_r3k_scanner"
VENV_PATH="$PROJECT_DIR/venv"
BRANCH="main"

echo "Starting deployment (SYSTEMD MODE)..."

cd "$PROJECT_DIR" || { echo "ERROR: Project folder not found: $PROJECT_DIR" >&2; exit 1; }

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
  sentinel.py \
  execution.py \
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
  echo "ERROR: Missing gate script: $PROJECT_DIR/bin/check_watchlist_today.sh" >&2
  echo "Fix: ensure repo deployed and script is executable." >&2
  exit 1
fi

echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Restarting services (systemd-managed)..."
sudo systemctl restart sentinel.service
sudo systemctl restart execution.service

echo "Verifying timers..."
sudo systemctl restart scan.timer execution-restart.timer >/dev/null 2>&1 || true
systemctl list-timers --all | grep -E 'scan\.timer|execution-restart\.timer|NEXT|LEFT' || true

echo "Deployment complete (SYSTEMD MODE)."
echo "Useful commands:"
echo "  systemctl status sentinel.service execution.service --no-pager"
echo "  journalctl -u sentinel.service -u execution.service --since 'today' --no-pager"

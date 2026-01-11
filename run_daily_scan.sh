#!/bin/bash
set -euo pipefail

# Navigate to project directory
cd "/Users/kevinvanhimbergen/avwap_r3k_scanner/" || exit 1

# 1. Smarter Path Detection (works on Linux and Mac)
PY="./venv/bin/python"
[ ! -x "$PY" ] && PY="./.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "ERROR: Virtual environment not found."
  exit 1
fi

DAY=$(date +%u)

# 2. Automated Rebuild for Scheduled Runs
# If you run this via a cron job, it won't be "interactive." 
# This checks if the script is running in a terminal.
if [ -t 0 ] && [ "$DAY" -ge 6 ]; then
  read -p "Rebuild Liquidity Snapshot? (y/n): " REBUILD
  if [ "${REBUILD}" == "y" ]; then
    rm -f cache/liquidity_snapshot.parquet
  fi
fi

# 3. Run the Scanner
"$PY" run_scan.py

# 4. OS-Aware Opening
if [ -f "daily_candidates.csv" ]; then
  echo "Scan Complete."
  # Only try to 'open' if on macOS
  if [[ "$OSTYPE" == "darwin"* ]]; then
    open daily_candidates.csv
  fi
else
  echo "No candidates found."
fi
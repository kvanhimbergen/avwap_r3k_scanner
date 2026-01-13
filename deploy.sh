#!/bin/bash
set -euo pipefail

# ----------------------------
# Configuration
# ----------------------------
PROJECT_DIR="/root/avwap_r3k_scanner"
VENV_PATH="$PROJECT_DIR/venv"
BRANCH="main"

SENTINEL_SESSION="scanner"
EXECUTION_SESSION="execution"

echo "🚀 Starting Deployment..."

# ----------------------------
# 1. Navigate to project
# ----------------------------
cd "$PROJECT_DIR" || { echo "❌ Project folder not found!"; exit 1; }

# ----------------------------
# 2. Pull latest code
# ----------------------------
echo "📥 Pulling latest code from $BRANCH..."
git checkout "$BRANCH" >/dev/null 2>&1 || true
git pull origin "$BRANCH"

# ----------------------------
# 3. Activate venv & update deps
# ----------------------------
echo "📦 Updating Python libraries..."
source "$VENV_PATH/bin/activate"
pip install -r requirements.txt

# ----------------------------
# 4. Fast-fail compile check
# ----------------------------
echo "🧪 Running Python compile checks..."
python -m py_compile \
  universe.py \
  run_scan.py \
  sentinel.py \
  execution.py \
  config.py

# ----------------------------
# 5. Ensure cache directory exists (do NOT delete universe cache)
# ----------------------------
mkdir -p "$PROJECT_DIR/cache"
if [ -f "$PROJECT_DIR/cache/iwv_holdings.csv" ]; then
  echo "✅ Universe cache present: cache/iwv_holdings.csv"
else
  echo "⚠️ Universe cache missing!"
  echo "   This droplet cannot fetch iShares; seed via scp from your Mac."
fi

# ----------------------------
# 6. Restart Sentinel (monitoring)
# ----------------------------
echo "🔄 Restarting Sentinel in tmux session: $SENTINEL_SESSION..."
tmux kill-session -t "$SENTINEL_SESSION" 2>/dev/null || true

tmux new-session -d -s "$SENTINEL_SESSION" \
  "cd \"$PROJECT_DIR\" && \
   set -a && [ -f .env ] && . .env && set +a && \
   export TEST_MODE=0 && unset TEST_MAX_TICKERS || true && \
   \"$VENV_PATH/bin/python\" -u sentinel.py >> \"$PROJECT_DIR/sentinel.log\" 2>&1"

# ----------------------------
# 7. Restart Execution Bot
# ----------------------------
echo "🔄 Restarting Execution Bot in tmux session: $EXECUTION_SESSION..."
tmux kill-session -t "$EXECUTION_SESSION" 2>/dev/null || true

tmux new-session -d -s "$EXECUTION_SESSION" \
  "cd \"$PROJECT_DIR\" && \
   set -a && [ -f .env ] && . .env && set +a && \
   export TEST_MODE=0 && unset TEST_MAX_TICKERS || true && \
   \"$VENV_PATH/bin/python\" -u execution.py >> \"$PROJECT_DIR/execution.log\" 2>&1"

# ----------------------------
# 8. Done
# ----------------------------
echo "✅ Deployment Complete!"
echo "📡 Sentinel running in tmux session: $SENTINEL_SESSION"
echo "💸 Execution bot running in tmux session: $EXECUTION_SESSION"
echo
echo "Useful commands:"
echo "  tmux ls"
echo "  tmux attach -t $SENTINEL_SESSION"
echo "  tmux attach -t $EXECUTION_SESSION"
echo "  tail -f sentinel.log"
echo "  tail -f execution.log"

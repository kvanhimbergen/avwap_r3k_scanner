#!/bin/bash
# --- Configuration ---
PROJECT_DIR="/root/avwap_r3k_scanner"
TMUX_SESSION="scanner"
VENV_PATH="$PROJECT_DIR/venv"
BRANCH="main"

echo "🚀 Starting Deployment..."

# 1. Navigate to project
cd "$PROJECT_DIR" || { echo "❌ Folder not found!"; exit 1; }

# 2. Pull latest code from GitHub
echo "📥 Pulling latest code from $BRANCH..."
git pull origin "$BRANCH"

# 3. Update dependencies
echo "📦 Updating Python libraries..."
source "$VENV_PATH/bin/activate"
pip install -r requirements.txt

# 4. Restart the background session
echo "🔄 Restarting Sentinel in tmux session: $TMUX_SESSION..."

# Kill the old session if it exists to refresh everything
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null

# Start a new detached session and run the sentinel
# We use 'bash -c' to ensure the venv stays active inside the session"
tmux new-session -d -s "$TMUX_SESSION" "cd \"$PROJECT_DIR\" && set -a && [ -f \"$PROJECT_DIR/.env\" ] && . \"$PROJECT_DIR/.env\" && set +a && \"$VENV_PATH/bin/python\" -u sentinel.py >> \"$PROJECT_DIR/sentinel.log\" 2>&1"



echo "✅ Deployment Complete! Sentinel is now running in the background."
echo "💡 Use 'tmux attach -t $TMUX_SESSION' to see live logs."

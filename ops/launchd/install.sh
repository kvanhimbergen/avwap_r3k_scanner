#!/usr/bin/env bash
# Install AVWAP launchd agents for the current user.
#
# What it does:
#   1. Creates ~/Library/Logs/avwap/ for log output
#   2. Makes the env wrapper executable
#   3. Copies plists to ~/Library/LaunchAgents/
#   4. Bootstraps (loads) both agents via launchctl
#
# Usage:  bash ops/launchd/install.sh
#
# To unload later:
#   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.avwap.scan.plist
#   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.avwap.post-scan.plist

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/avwap"
UID_VAL="$(id -u)"

echo "==> Creating log directory: $LOG_DIR"
mkdir -p "$LOG_DIR"

echo "==> Making wrapper script executable"
chmod +x "$SCRIPT_DIR/run_with_env.sh"

echo "==> Copying plists to $LAUNCH_AGENTS"
mkdir -p "$LAUNCH_AGENTS"
cp "$SCRIPT_DIR/com.avwap.scan.plist" "$LAUNCH_AGENTS/"
cp "$SCRIPT_DIR/com.avwap.post-scan.plist" "$LAUNCH_AGENTS/"

# Unload first (ignore errors if not loaded)
echo "==> Unloading existing agents (if any)"
launchctl bootout "gui/$UID_VAL/$LAUNCH_AGENTS/com.avwap.scan.plist" 2>/dev/null || true
launchctl bootout "gui/$UID_VAL/$LAUNCH_AGENTS/com.avwap.post-scan.plist" 2>/dev/null || true

echo "==> Loading agents"
launchctl bootstrap "gui/$UID_VAL" "$LAUNCH_AGENTS/com.avwap.scan.plist"
launchctl bootstrap "gui/$UID_VAL" "$LAUNCH_AGENTS/com.avwap.post-scan.plist"

echo "==> Verifying"
launchctl list | grep avwap || echo "WARNING: agents not found in launchctl list"

echo ""
echo "Done. Both agents are loaded and will fire on weekday mornings."
echo "Logs: $LOG_DIR/scan.log and $LOG_DIR/post-scan.log"
echo ""
echo "Don't forget to set the Mac wake schedule:"
echo "  sudo pmset repeat wakeorpoweron MTWRF 08:25:00"

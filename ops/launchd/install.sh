#!/usr/bin/env bash
# Install AVWAP launchd agents for the current user.
#
# What it does:
#   1. Creates ~/Library/Logs/avwap/ for log output
#   2. Makes the env wrapper executable
#   3. Copies plists to ~/Library/LaunchAgents/
#   4. Bootstraps (loads) all agents via launchctl
#
# Usage:  bash ops/launchd/install.sh
#
# To unload later:
#   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.avwap.scan.plist
#   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.avwap.post-scan.plist
#   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.avwap.analytics-platform.plist
#   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.avwap.tunnel.plist

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/avwap"
UID_VAL="$(id -u)"

PLISTS=(
    com.avwap.scan
    com.avwap.post-scan
    com.avwap.analytics-platform
    com.avwap.tunnel
)

echo "==> Creating log directory: $LOG_DIR"
mkdir -p "$LOG_DIR"

echo "==> Making wrapper script executable"
chmod +x "$SCRIPT_DIR/run_with_env.sh"

echo "==> Copying plists to $LAUNCH_AGENTS"
mkdir -p "$LAUNCH_AGENTS"
for label in "${PLISTS[@]}"; do
    cp "$SCRIPT_DIR/${label}.plist" "$LAUNCH_AGENTS/"
done

# Unload first (ignore errors if not loaded)
echo "==> Unloading existing agents (if any)"
for label in "${PLISTS[@]}"; do
    launchctl bootout "gui/$UID_VAL/${label}" 2>/dev/null || true
done

echo "==> Loading agents"
for label in "${PLISTS[@]}"; do
    launchctl bootstrap "gui/$UID_VAL" "$LAUNCH_AGENTS/${label}.plist"
done

echo "==> Verifying"
launchctl list | grep avwap || echo "WARNING: agents not found in launchctl list"

echo ""
echo "Done. All agents are loaded."
echo "  Scheduled: scan (08:30 ET weekdays), post-scan (08:35 ET weekdays)"
echo "  KeepAlive: analytics-platform (port 8787), tunnel (cloudflared)"
echo "Logs: $LOG_DIR/"
echo ""
echo "Don't forget to set the Mac wake schedule:"
echo "  sudo pmset repeat wakeorpoweron MTWRF 08:25:00"

# Check cloudflared tunnel config
CONFIG_FILE="$SCRIPT_DIR/cloudflared-config.yml"
if grep -q '<TUNNEL-ID>' "$CONFIG_FILE" 2>/dev/null; then
    echo ""
    echo "WARNING: cloudflared-config.yml still has placeholder <TUNNEL-ID>."
    echo "Complete the one-time tunnel setup:"
    echo "  1. brew install cloudflared"
    echo "  2. cloudflared tunnel login"
    echo "  3. cloudflared tunnel create avwap"
    echo "  4. cloudflared tunnel route dns avwap avwap.vantagedutch.com"
    echo "  5. Edit ops/launchd/cloudflared-config.yml — replace <TUNNEL-ID> with the ID from step 3"
    echo "  6. Re-run: bash ops/launchd/install.sh"
fi

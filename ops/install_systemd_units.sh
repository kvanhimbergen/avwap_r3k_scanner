#!/usr/bin/env bash
set -euo pipefail

# Install systemd unit files + drop-ins from the repo into /etc/systemd/system.
# Intended to be run ON THE DROPLET (Ubuntu) after the repo is deployed to /root/avwap_r3k_scanner.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${REPO_ROOT}/ops/systemd"

require_file() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo "ERROR: missing file: $f" >&2
    exit 1
  fi
}

echo "Repo root: ${REPO_ROOT}"
echo "Source systemd dir: ${SRC_DIR}"

# Core units/timers
require_file "${SRC_DIR}/execution.service"
require_file "${SRC_DIR}/scan.service"
require_file "${SRC_DIR}/scan.timer"
require_file "${SRC_DIR}/execution-restart.service"
require_file "${SRC_DIR}/execution-restart.timer"
require_file "${SRC_DIR}/analytics-platform.service"
require_file "${SRC_DIR}/post-scan.service"
require_file "${SRC_DIR}/post-scan.timer"

# Drop-ins
require_file "${SRC_DIR}/execution.service.d/10-watchlist-gate.conf"
require_file "${SRC_DIR}/execution.service.d/20-restart-policy.conf"

echo "Copying unit files to /etc/systemd/system/ ..."
sudo install -m 0644 "${SRC_DIR}/execution.service" /etc/systemd/system/execution.service
sudo install -m 0644 "${SRC_DIR}/scan.service" /etc/systemd/system/scan.service
sudo install -m 0644 "${SRC_DIR}/scan.timer" /etc/systemd/system/scan.timer
sudo install -m 0644 "${SRC_DIR}/execution-restart.service" /etc/systemd/system/execution-restart.service
sudo install -m 0644 "${SRC_DIR}/execution-restart.timer" /etc/systemd/system/execution-restart.timer
sudo install -m 0644 "${SRC_DIR}/analytics-platform.service" /etc/systemd/system/analytics-platform.service
sudo install -m 0644 "${SRC_DIR}/post-scan.service" /etc/systemd/system/post-scan.service
sudo install -m 0644 "${SRC_DIR}/post-scan.timer" /etc/systemd/system/post-scan.timer

echo "Copying execution.service drop-ins ..."
sudo mkdir -p /etc/systemd/system/execution.service.d
sudo install -m 0644 "${SRC_DIR}/execution.service.d/10-watchlist-gate.conf" /etc/systemd/system/execution.service.d/10-watchlist-gate.conf
sudo install -m 0644 "${SRC_DIR}/execution.service.d/20-restart-policy.conf" /etc/systemd/system/execution.service.d/20-restart-policy.conf

echo "Reloading systemd ..."
sudo systemctl daemon-reload

echo "Enabling timers ..."
sudo systemctl enable --now scan.timer execution-restart.timer post-scan.timer

echo "Enabling services ..."
sudo systemctl enable execution.service
sudo systemctl enable analytics-platform.service

echo "Starting services (if not running) ..."
sudo systemctl start execution.service || true
sudo systemctl start analytics-platform.service || true

echo
echo "==== Status ===="
systemctl status execution.service analytics-platform.service --no-pager || true

echo
echo "==== Timers ===="
systemctl list-timers --all | grep -E 'scan\.timer|execution-restart\.timer|post-scan\.timer|NEXT|LEFT' || true

echo
echo "Install complete."

#!/usr/bin/env bash
# Wrapper that loads .env then execs the given command.
# launchd doesn't support EnvironmentFile like systemd, so both plists
# invoke their command through this script.
#
# Usage: run_with_env.sh venv/bin/python -u run_scan.py

set -euo pipefail

REPO_DIR="/Users/kevinvanhimbergen/avwap_r3k_scanner"
cd "$REPO_DIR"

set -a
# shellcheck source=/dev/null
source "$REPO_DIR/.env"
set +a

exec "$@"

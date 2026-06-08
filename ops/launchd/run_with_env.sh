#!/usr/bin/env bash
# Wrapper that loads .env then execs the given command.
# launchd doesn't support EnvironmentFile like systemd, so both plists
# invoke their command through this script.
#
# Usage: run_with_env.sh venv/bin/python -u run_scan.py

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

set -a
# shellcheck source=/dev/null
source "$REPO_DIR/.env"
set +a

# Ensure repo root is on sys.path so scripts invoked as `python ops/foo.py`
# (rather than `python -m ops.foo`) can still import top-level packages
# like `alerts`, `utils`, `analytics`. Without this, sys.path[0] is the
# script's directory and root-level imports fail.
export PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}"

exec "$@"

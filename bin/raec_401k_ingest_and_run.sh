#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/root/avwap_r3k_scanner"
VENV_PYTHON="${BASE_DIR}/venv/bin/python"
TODAY_NY="$(TZ=America/New_York date +%F)"

echo "=== RAEC 401(k) coordinator  asof=${TODAY_NY} ==="

exec "${VENV_PYTHON}" -m strategies.raec_401k_coordinator --asof "${TODAY_NY}"

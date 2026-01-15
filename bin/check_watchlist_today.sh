#!/usr/bin/env bash
set -euo pipefail

# Gate: ensure watchlist exists and is from "today" in America/New_York.
# Used by systemd ExecStartPre for execution.service.

WATCHLIST_FILE="${WATCHLIST_FILE:-daily_candidates.csv}"
BASE_DIR="/root/avwap_r3k_scanner"
FILE_PATH="${BASE_DIR}/${WATCHLIST_FILE}"

if [[ ! -f "${FILE_PATH}" ]]; then
  echo "Watchlist missing: ${FILE_PATH}" >&2
  exit 1
fi

MTIME_EPOCH="$(stat -c %Y "${FILE_PATH}")"
TODAY_NY="$(TZ=America/New_York date +%F)"
FILE_DATE_NY="$(TZ=America/New_York date -d "@${MTIME_EPOCH}" +%F)"

if [[ "${FILE_DATE_NY}" != "${TODAY_NY}" ]]; then
  echo "Watchlist is not from today (NY). file_date=${FILE_DATE_NY} today=${TODAY_NY} path=${FILE_PATH}" >&2
  exit 2
fi

echo "OK: Watchlist is fresh for today (NY): ${FILE_PATH} (${FILE_DATE_NY})"

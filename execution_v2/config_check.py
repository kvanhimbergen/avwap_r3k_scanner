"""
Offline-only execution configuration preflight.

This module is intentionally dependency-light so that it can run in minimal
environments without importing optional broker/data dependencies (alpaca, pandas,
yfinance, requests, etc.).

It is used by:
- `python -m execution_v2.config_check` (standalone preflight)
- `execution_v2.execution_main --config-check` (delegates here)
- `python -m tools.avwap_check` (delegates here)
"""

from __future__ import annotations

import os
from pathlib import Path

from execution_v2 import live_gate

from execution_v2.state_helpers import (  # noqa: E402
    DEFAULT_STATE_DIR,
    resolve_execution_mode as _resolve_execution_mode,
    state_dir as _state_dir,
)

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def _normalize_base_url(url: str) -> str:
    # Minimal normalization to avoid importing heavier helpers.
    return url.strip().rstrip("/")




def run_config_check(state_dir: str | None = None) -> tuple[bool, list[str]]:
    """
    Returns (ok, issues). Offline-only.
    """
    issues: list[str] = []
    mode = _resolve_execution_mode()
    resolved_state_dir = Path(state_dir) if state_dir else _state_dir()

    if str(resolved_state_dir).strip() == "":
        issues.append("state_dir_missing")
    else:
        try:
            resolved_state_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            issues.append(f"state_dir_unwritable:{exc}")

    if mode in {"LIVE", "ALPACA_PAPER"}:
        if not os.getenv("APCA_API_KEY_ID"):
            issues.append("missing:APCA_API_KEY_ID")
        if not os.getenv("APCA_API_SECRET_KEY"):
            issues.append("missing:APCA_API_SECRET_KEY")

    if mode == "ALPACA_PAPER":
        base_url = os.getenv("APCA_API_BASE_URL") or ""
        if not base_url:
            issues.append("missing:APCA_API_BASE_URL")
        else:
            normalized = _normalize_base_url(base_url)
            if normalized != PAPER_BASE_URL:
                issues.append(f"invalid:APCA_API_BASE_URL({base_url})")

    if mode == "LIVE" and os.getenv("LIVE_TRADING", "0") == "1":
        enabled, reason = live_gate.live_trading_enabled(str(resolved_state_dir))
        if not enabled:
            issues.append(f"live_trading_disabled:{reason}")
        if live_gate._phase_c_enabled():
            live_enable_date_ny = os.getenv("LIVE_ENABLE_DATE_NY", "").strip()
            if not live_enable_date_ny:
                issues.append("missing:LIVE_ENABLE_DATE_NY")
            allowlist = live_gate.parse_allowlist()
            if not allowlist or len(allowlist) != 1:
                issues.append("invalid:ALLOWLIST_SYMBOLS_phase_c")

    return (len(issues) == 0, issues)


def main() -> int:
    ok, issues = run_config_check()
    if ok:
        print("PASS")
        return 0
    print("FAIL")
    for issue in issues:
        print(issue)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

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

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
DEFAULT_STATE_DIR = "/root/avwap_r3k_scanner/state"


def _state_dir() -> Path:
    base = os.getenv("AVWAP_STATE_DIR", DEFAULT_STATE_DIR).strip()
    if not base:
        base = DEFAULT_STATE_DIR
    return Path(base)


def _normalize_base_url(url: str) -> str:
    # Minimal normalization to avoid importing heavier helpers.
    return url.strip().rstrip("/")


def _resolve_execution_mode() -> str:
    env_mode = os.getenv("EXECUTION_MODE")
    dry_run_env = os.getenv("DRY_RUN", "0") == "1"
    valid_modes = {"DRY_RUN", "PAPER_SIM", "LIVE", "ALPACA_PAPER", "SCHWAB_401K_MANUAL"}

    if env_mode:
        mode = env_mode.strip().upper()
        if mode not in valid_modes:
            return "DRY_RUN" if dry_run_env else "LIVE"
        if mode != "DRY_RUN" and dry_run_env:
            return "DRY_RUN"
        return mode

    return "DRY_RUN" if dry_run_env else "LIVE"


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

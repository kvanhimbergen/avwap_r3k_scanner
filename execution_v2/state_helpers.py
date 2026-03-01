"""Shared state directory helpers for execution_v2 modules."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIR = str(_REPO_ROOT / "state")


def state_dir() -> Path:
    base = os.getenv("AVWAP_STATE_DIR", DEFAULT_STATE_DIR).strip()
    if not base:
        base = DEFAULT_STATE_DIR
    return Path(base)


VALID_EXECUTION_MODES = {"DRY_RUN", "PAPER_SIM", "LIVE", "ALPACA_PAPER", "SCHWAB_401K_MANUAL"}


def resolve_execution_mode() -> str:
    env_mode = os.getenv("EXECUTION_MODE")
    dry_run_env = os.getenv("DRY_RUN", "0") == "1"

    if env_mode:
        mode = env_mode.strip().upper()
        if mode not in VALID_EXECUTION_MODES:
            return "DRY_RUN" if dry_run_env else "LIVE"
        if mode != "DRY_RUN" and dry_run_env:
            return "DRY_RUN"
        return mode

    return "DRY_RUN" if dry_run_env else "LIVE"

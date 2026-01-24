"""Book identifiers and ledger routing helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

ALPACA_PAPER = "ALPACA_PAPER"
ALPACA_LIVE = "ALPACA_LIVE"
SCHWAB_401K_MANUAL = "SCHWAB_401K_MANUAL"


def resolve_book_id(execution_mode: str) -> Optional[str]:
    mode = execution_mode.strip().upper()
    if mode == "ALPACA_PAPER":
        return ALPACA_PAPER
    if mode == "LIVE":
        return ALPACA_LIVE
    if mode == SCHWAB_401K_MANUAL:
        return SCHWAB_401K_MANUAL
    return None


def ledger_path(repo_root: Path, book_id: str, date_ny: str) -> Path:
    return repo_root / "ledger" / book_id / f"{date_ny}.jsonl"

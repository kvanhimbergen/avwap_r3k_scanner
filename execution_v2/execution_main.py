"""
Execution V2 – Orchestration Entrypoint (dry-run first)

Responsibilities:
- Build MarketContext
- Ingest daily watchlist into candidates
- Evaluate entries (BOH + regime-gated) → entry intents
- Evaluate positions → trim intents / stop escalation
- Execute due intents with idempotency (broker submit later)
- Restart-safe, systemd-friendly
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Optional

from execution_v2.config_types import MarketContext, GlobalRegime
from execution_v2 import clocks
from execution_v2 import market_data
from execution_v2.state_store import StateStore
from execution_v2 import buy_loop, sell_loop


def _env_flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _account_equity() -> float:
    """
    Account equity is injected via env for now.
    This avoids broker coupling in dry-run / shadow mode.
    """
    v = os.getenv("EXECUTION_V2_ACCOUNT_EQUITY")
    if not v:
        raise RuntimeError("EXECUTION_V2_ACCOUNT_EQUITY must be set")
    return float(v)


def _build_market_context() -> MarketContext:
    snap = clocks.now_snapshot()
    return MarketContext(
        now_ts=snap.now_ts,
        market_open=snap.market_open,
        entry_window_open=snap.entry_window_open,
        global_regime=GlobalRegime.NORMAL,
    )


def run_once(store: StateStore, md: market_data.MarketData, dry_run: bool) -> None:
    ctx = _build_market_context()

    # ---- BUY SIDE ----
    buy_cfg = buy_loop.BuyLoopConfig()
    buy_loop.ingest_watchlist_as_candidates(store, buy_cfg)

    if ctx.market_open and ctx.entry_window_open:
        buy_loop.evaluate_and_create_entry_intents(
            store=store,
            md=md,
            cfg=buy_cfg,
            account_equity=_account_equity(),
        )

    # ---- SELL SIDE ----
    sell_cfg = sell_loop.SellLoopConfig()
    sell_loop.evaluate_positions(
        store=store,
        md=md,
        cfg=sell_cfg,
    )

    # ---- EXECUTION (dry-run only) ----
    now_ts = time.time()
    due_entries = store.pop_due_entry_intents(now_ts)

    for intent in due_entries:
        # idempotency + broker submission will be added later
        print(f"[DRY RUN] ENTRY {intent.symbol} size={intent.size_shares}")


def main() -> int:
    p = argparse.ArgumentParser("Execution V2 Orchestrator")
    p.add_argument("--db", default=os.getenv("EXECUTION_V2_DB", "execution_v2.sqlite"))
    p.add_argument("--poll-seconds", type=int, default=15)
    p.add_argument("--dry-run", action="store_true", default=_env_flag("EXECUTION_V2_DRY_RUN", True))
    p.add_argument("--once", action="store_true")
    args = p.parse_args()

    store = StateStore(args.db)
    md = market_data.from_env()

    if args.once:
        run_once(store, md, dry_run=args.dry_run)
        return 0

    while True:
        try:
            run_once(store, md, dry_run=args.dry_run)
            time.sleep(args.poll_seconds)
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(f"[execution_v2] error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
# Execution V2 placeholder: execution_main.py

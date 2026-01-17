# Execution V2 placeholder: buy_loop.py
"""
Execution V2 – Buy Loop
Schedules entry intents from watchlist symbols using BOH + regime gating.
"""

from time import time
from execution_v2.config_types import EntryIntent

class BuyLoopConfig:
    """
    Configuration for buy-loop operations.
    """
    def __init__(self):
        self.watchlist = ['SPY', 'AAPL', 'QQQ', 'TSLA', 'AMZN']
        self.symbol_regime = None
        self.sizing = None

def ingest_watchlist_as_candidates(store, cfg: BuyLoopConfig):
    """
    Inserts watchlist symbols into candidates table.
    """
    now_ts = time()
    for sym in cfg.watchlist:
        store.upsert_candidate(
            symbol=sym,
            first_seen_ts=now_ts,
            expires_ts=now_ts + 3600,
            pivot_level=None,
            notes="watchlist ingest"
        )

def evaluate_and_create_entry_intents(store, md, cfg, account_equity):
    """
    Minimal stub: create one dummy intent per candidate for dry-run.
    """
    now_ts = time()
    symbols = store.list_active_candidates(now_ts)
    for sym in symbols:
        intent = EntryIntent(
            symbol=sym,
            pivot_level=100.0,
            boh_confirmed_at=now_ts,
            scheduled_entry_at=now_ts + 10,
            size_shares=1
        )
        store.put_entry_intent(intent)



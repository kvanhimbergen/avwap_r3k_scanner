"""
Execution V2 – Orchestration Entrypoint (dry-run)
"""

from time import time
from execution_v2.state_store import StateStore
from execution_v2 import buy_loop, sell_loop

def run_once():
    store = StateStore('execution_v2.sqlite')
    buy_cfg = buy_loop.BuyLoopConfig()
    sell_cfg = sell_loop.SellLoopConfig()

    # Ingest candidates
    buy_loop.ingest_watchlist_as_candidates(store, buy_cfg)

    # Evaluate buy side
    buy_loop.evaluate_and_create_entry_intents(store, md=None, cfg=buy_cfg, account_equity=100000)

    # Evaluate sell side
    sell_loop.evaluate_positions(store, md=None, cfg=sell_cfg)

if __name__ == "__main__":
    run_once()
    print("Execution V2 dry-run complete")

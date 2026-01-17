"""
Execution V2 – Sell Loop
Evaluates positions for potential trim / stop action.
"""

from execution_v2.config_types import StopMode

class SellLoopConfig:
    """
    Stub config for sell-loop operations.
    """
    def __init__(self):
        self.trim_pct = 0.25  # example placeholder

def evaluate_positions(store, md, cfg):
    """
    Minimal dry-run stub to print positions.
    """
    positions = store.list_positions()
    for p in positions:
        if isinstance(p, str):
            # Fix for old DB misalignment
            symbol = p
            stop_mode = StopMode.UNKNOWN
        else:
            symbol = p.symbol
            stop_mode = p.stop_mode
        print(f"[DRY RUN] SELL LOOP: {symbol} stop_mode={stop_mode.name}")

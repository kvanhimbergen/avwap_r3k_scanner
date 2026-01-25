#!/usr/bin/env python
"""
Repro: ledger write failure for dry-run ledger.
"""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from execution_v2 import execution_main


def main() -> None:
    state_dir = tempfile.mkdtemp(prefix="avwap_state_")
    os.chmod(state_dir, 0o555)
    os.environ["AVWAP_STATE_DIR"] = state_dir

    intent = SimpleNamespace(symbol="AAPL", size_shares=1)
    result = execution_main._submit_market_entry(None, intent, dry_run=True)
    ledger_path = os.path.join(state_dir, "dry_run_ledger.json")
    print("result:", result)
    print("ledger_exists:", os.path.exists(ledger_path))


if __name__ == "__main__":
    main()

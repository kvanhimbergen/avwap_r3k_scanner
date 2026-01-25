#!/usr/bin/env python
"""
Repro: edge-case market data for exit simulator (missing bars).
"""

from __future__ import annotations

from execution_v2.exit_simulator import simulate_exit


def main() -> None:
    events = simulate_exit(
        symbol="TEST",
        entry_price=10.0,
        qty=5,
        entry_ts_utc="2024-01-02T14:30:00+00:00",
        intraday_bars=[],
        daily_bars=[],
        stop_buffer_dollars=0.1,
    )
    print("events:", events)


if __name__ == "__main__":
    main()

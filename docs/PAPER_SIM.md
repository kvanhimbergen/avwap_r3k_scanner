# Execution V2 Paper Simulation

## Overview
`PAPER_SIM` is a deterministic, replayable execution mode that writes simulated fill events to a JSONL ledger. It is **not** broker paper trading, and it does not submit Alpaca orders.

## Enabling
Set the execution mode via environment variable:

```
EXECUTION_MODE=PAPER_SIM
```

For Alpaca paper trading:

```
EXECUTION_MODE=ALPACA_PAPER
ALPACA_API_KEY_PAPER=...
ALPACA_API_SECRET_PAPER=...
ALPACA_BASE_URL_PAPER=https://paper-api.alpaca.markets
```

If `EXECUTION_MODE` is unset, Execution V2 preserves the existing behavior:

- `DRY_RUN=1` ⇒ DRY_RUN
- otherwise ⇒ LIVE

Safety: when `DRY_RUN=1`, LIVE cannot be enabled accidentally even if `EXECUTION_MODE=LIVE` is set.

## Execution modes comparison

| Mode | Uses Alpaca broker | Uses synthetic fills | Ledger location | When to use |
| --- | --- | --- | --- | --- |
| DRY_RUN | No | Yes (logging only) | `/root/avwap_r3k_scanner/state/dry_run_ledger.json` | Safe no-order validation of scheduling/gates. |
| PAPER_SIM | No | Yes (deterministic fills) | `ledger/PAPER_SIM/<YYYY-MM-DD>.jsonl` | Deterministic evaluation of fills/positions/PnL. |
| ALPACA_PAPER | Yes (paper keys/base URL) | No | `ledger/ALPACA_PAPER/<YYYY-MM-DD>.jsonl` | Broker-integrated paper trading with real order status/fills. |
| LIVE | Yes (live keys) | No | Live broker only (no persistent ledger) | Production execution. |

## When to use which mode

- **PAPER_SIM** for deterministic, replayable evaluation without broker I/O.
- **ALPACA_PAPER** when you want actual Alpaca paper orders/fills but still no live risk.
- **LIVE** for real trading only after safety gates are satisfied.

## Ledger location
Fills are appended to:

```
ledger/PAPER_SIM/<YYYY-MM-DD>.jsonl
```

Each line is a JSON object with:

```
{
  "ts_utc": "...",
  "date_ny": "YYYY-MM-DD",
  "mode": "PAPER_SIM",
  "event_type": "FILL_SIMULATED",
  "intent_id": "...",
  "symbol": "...",
  "side": "BUY",
  "qty": 123,
  "price": 45.67,
  "source": "intent_entry_price|daily_candidates_entry_level|latest_close_cache"
}
```

## Idempotency
Before writing, the ledger is scanned for existing `intent_id` values. If a fill with the same `intent_id` already exists, it is skipped and not duplicated. The `intent_id` is deterministic:

- If the intent already has an `intent_id`, that is used.
- Otherwise, it is a SHA-256 hash of `(date_ny, symbol, side, qty, rounded_price, "PAPER_SIM")`.

## Pricing fallback order
1. `intent.entry_price` (or equivalent, e.g. `entry_level`/`ref_price`) if present.
2. `Entry_Level` from `daily_candidates.csv` (matching `ScanDate` and `Symbol`).
3. Latest cached close from `cache/ohlcv_history.parquet` (if available).

If no price can be resolved, `PAPER_SIM` raises a clear error.

## Sizing note
`PAPER_SIM` uses `PAPER_SIM_EQUITY` (default: `100000`) when sizing new entry intents because it does not query broker account equity.

## Status CLI
Use the status helper to inspect fills/positions:

```
python scripts/paper_sim_status.py --date-ny YYYY-MM-DD
```

It reports the number of fills, unique symbols, derived positions, and unrealized PnL when mark prices are available.

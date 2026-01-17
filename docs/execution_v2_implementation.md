# Execution V2 Overview

## Purpose
Execution V2 is a modular, restart-safe Python trading orchestration engine designed for managing retail equity trades using technical triggers. It supports **dry-run testing** and **real execution** via Alpaca, with a **single-writer SQLite database** for state persistence.

---

## Directory Structure
execution_v2/
├── init.py
├── buy_loop.py
├── sell_loop.py
├── clocks.py
├── config_types.py
├── execution_main.py
├── market_data.py
├── state_store.py
├── alerts.py
├── boh.py
├── orders.py
├── pivots.py
├── regime_global.py
├── regime_symbol.py
└── sizing.py

yaml
Copy code

---

## Files & Responsibilities

### 1. `state_store.py`
- Manages persistent SQLite DB state.
- Tables:
  - `candidates`: symbols available for potential entry.
  - `entry_intents`: scheduled trade intents after BOH confirmation.
  - `positions`: active positions with size, price, and stop levels.
  - `order_ledger`: idempotency tracking of executed orders.
- Provides methods:
  - `upsert_candidate()`, `list_active_candidates()`
  - `put_entry_intent()`, `pop_due_entry_intents()`
  - `upsert_position()`, `list_positions()`
  - `record_order_once()`, `update_external_order_id()`

---

### 2. `config_types.py`
- Defines canonical, immutable data contracts.
- Key classes:
  - `EntryIntent`: planned trade execution (symbol, entry level, BOH timestamps, schedule, size, stop, target, ref price).
  - `PositionState`: active position state (size, avg price, pivot, stop levels, trim flags).
  - `MarketContext`: snapshot of market and regime conditions.
  - `GlobalRegime` & `SymbolRegime`: execution gating based on market/technical state.
  - `StopMode`: position risk/exit state.

---

### 3. `buy_loop.py`
- Loads scan candidates from `daily_candidates.csv`.
- Ingests scan symbols into `candidates` table.
- Evaluates candidate symbols:
  - Requires BOH confirmation using last two closed 10-minute bars.
  - Creates `EntryIntent` records with sizing, stop, and target metadata.
- Main methods:
  - `ingest_watchlist_as_candidates(store, cfg)`
  - `evaluate_and_create_entry_intents(store, md, cfg, account_equity)`
- `BuyLoopConfig` defines CSV path, entry delays, and sizing parameters.

---

### 4. `sell_loop.py`
- Evaluates positions and determines trim/exit intents.
- Implements R1/R2-based trims and trailing-stop exits.
- `SellLoopConfig` provides trim sizing and trailing configuration.

---

### 5. `execution_main.py`
- Orchestration entrypoint (polling loop or `--once`).
- Responsibilities:
  1. Build `MarketContext` snapshot.
  2. Ingest daily scan output into candidates.
  3. Run `buy_loop` to evaluate entries → create `entry_intents`.
  4. Run `sell_loop` to evaluate positions → trim intents / stop escalation.
  5. Execute due intents from DB (dry-run or live via Alpaca via bracket orders).
  6. Restart-safe with idempotency via `order_ledger`.
- Supports CLI:
  - `--dry-run` (default)
  - `--once` (single cycle)
  - `--poll-seconds` (for continuous execution)
  - `--candidates-csv` (daily scan output path)

---

### 6. `market_data.py`
- Adapter for market data (Alpaca).
- Provides:
  - `MarketData` class for daily bars (pivot/global regime) and 10-minute bars (BOH confirmation).
  - `from_env()` constructor using environment API credentials.

---

### Execution Flow (Dry-Run)
1. Build `MarketContext`.
2. Insert daily scan symbols into `candidates`.
3. Evaluate `candidates` using `buy_loop` → create `entry_intents` after BOH confirmation.
4. Evaluate `positions` using `sell_loop` → dry-run stop/trim logic.
5. Pop and display due `entry_intents`.
6. All DB writes are restart-safe; idempotency prevents duplicates.

---

### Notes
- SQLite DB: `data/execution_v2.sqlite` stored in repo `/data` directory.
- Dry-run ensures safe testing without submitting real orders.
- All `EntryIntent` and `PositionState` objects are strongly typed and immutable where applicable.
- `StateStore` handles all database migrations automatically.

### Daily Candidates Schema (v1)
Execution V2 expects the scan output `daily_candidates.csv` to include (at minimum):
- `SchemaVersion`
- `ScanDate`
- `Symbol`
- `Direction`
- `Price`
- `Entry_Level`
- `Entry_DistPct`
- `Stop_Loss`
- `Target_R2`

Optional fields (used for context but not required for execution):
- `Target_R1`
- `Anchor`
- `TrendTier`, `RS`, `Sector`
- `Setup_*` context fields

---

**End of Execution V2 Overview**

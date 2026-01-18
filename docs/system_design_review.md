# AVWAP R3K Scanner — Current System Design Review

## Overview
The system is a daily scan-and-execute pipeline for Russell 3000 candidates. It builds a tradable universe, filters by liquidity and market regime, scores anchors (AVWAP) with relative strength and trend gates, outputs a candidates CSV, and feeds execution_v2. Alerts are sent via Slack webhooks for scan completion and execution events.

## High-level data flow
1. **Universe build**: download and cache IWV holdings, normalize, apply YAML-driven liquidity rules using a `cfg.get_universe_metrics()` provider. (See `universe.py` and `config.py`.)
2. **Market regime + liquidity snapshot**: check SPY above SMA200 and build a sector/RS-weighted liquidity snapshot via Alpaca data. (See `run_scan.py`.)
3. **Historical OHLCV cache**: refresh/append to a Parquet cache for daily bars. (See `cache_store.py` + `run_scan.py`.)
4. **Scan + gating**: earnings filter (cached), weekly alignment, Shannon quality gates (SMA/ATR-based), anchor selection, setup context, stop/target derivation. (See `run_scan.py`, `anchors.py`, `indicators.py`, `setup_context.py`.)
5. **Output**: `daily_candidates.csv` + TradingView watchlist file. Slack alert sent. (See `run_scan.py` + `alerts/slack.py`.)
6. **Execution**: `execution_v2` consumes the candidates CSV and places orders via Alpaca (Execution v1 is deprecated). (See `execution_v2/*`.)

---

## Core components (by responsibility)

### 1) Universe + liquidity rules
- **Universe source**: IWV holdings downloaded from iShares with a local cache fallback. (`universe.py`)
- **Rules**: YAML-driven liquidity rules apply minimum price/volume thresholds. (`universe.py`)
- **Metrics provider**: `cfg.get_universe_metrics()` uses yfinance to fetch 1-month daily data for price/volume metrics. (`config.py`)

### 2) Market regime & liquidity snapshot
- **Regime**: scan runs only when SPY is above its 200-day SMA (fail-open on errors). (`run_scan.py`)
- **Liquidity snapshot**: for each valid ticker, daily bars are pulled from Alpaca to compute average dollar volume and relative strength; the snapshot is sector-ranked and capped. (`run_scan.py`)

### 3) Historical OHLCV cache
- **Storage**: Parquet cache stored under `cache/ohlcv_history.parquet` with atomic writes and type downcasting. (`cache_store.py`)
- **Refresh**: daily refresh pulls only the last ~15 days unless the cache is missing (backfills 2 years). (`run_scan.py`)

### 4) Scan logic & scoring
- **Earnings gate**: yfinance-based earnings check with disk cache and TTL controls. (`run_scan.py`)
- **Trend and volatility gates**: Shannon-style gates check SMA alignment, ATR minimums, ATR percentile vs median, etc. (`run_scan.py`)
- **Anchor selection**: AVWAP anchors are evaluated for slope, reclaim behavior, distance to AVWAP, and RS scoring. (In both `run_scan.py` and `scanner.py`.)
- **Setup context**: calculates VWAP/AVWAP control and acceptance states, extension state, and structure regime, driven by YAML rules. (`setup_context.py`)
- **Stop/targets**: structural stop based on 5-day SMA/low with buffer, pivot targets via `get_pivot_targets`. (`run_scan.py`, `indicators.py`)

### 5) Output artifacts
- **Primary output**: `daily_candidates.csv` with schema fields for direction, entry/stop/targets, RS, AVWAP metadata, and setup context. (`run_scan.py`)
- **Secondary output**: `tradingview_watchlist.txt` from the same candidates file. (`run_scan.py`)
- **Alerts**: Slack webhook alerts for scan completion and execution events. (`alerts/slack.py`)

### 6) Execution engines
- **Execution v1** (`execution.py`, deprecated): legacy polling loop with market-open guard, basic risk sizing, and bracket order placement; tracks in-memory order updates. The watchlist file is used directly.
- **Execution v2** (`execution_v2/*`): active modularized orchestration with
  - **State store**: SQLite with schema versioning, idempotency ledger, and persistent entry/trim intents. (`execution_v2/state_store.py`)
  - **Buy loop**: reads `daily_candidates.csv`, BOH confirms on 10-minute bars, sizes position, and schedules entry intents. (`execution_v2/buy_loop.py`, `execution_v2/boh.py`, `execution_v2/sizing.py`, `execution_v2/market_data.py`)
  - **Sell loop**: manages trims/stop exits based on R1/R2 and trailing logic. (`execution_v2/sell_loop.py`)
  - **Orchestration**: polls market hours, places orders, and manages dry-run ledger. (`execution_v2/execution_main.py`)

---

## Potential gaps in execution

### Data & caching
- **Dual scanning paths**: `run_scan.py` is the active scan pipeline; `scanner.py` has been deprecated to avoid drift between implementations.
- **Silent error handling**: several `try/except: continue` blocks (e.g., snapshot refresh, earnings checks) can mask systemic data failures and create incomplete candidate sets without clear logs.
- **Market regime fail-open**: if the SPY SMA check fails, the scan proceeds by default, potentially enabling scans during incorrect conditions.

### Execution
- **Parallel execution engines**: both `execution.py` and `execution_v2` exist; without a clear toggle or deprecation, the system risks diverging behaviors and duplicated fixes.
- **Order risk controls**: v2 adds idempotency and persistent state, but v1 still uses only in-memory tracking. If both are accidentally running, double orders are possible.
- **Entry gating coverage**: v2 uses BOH confirmation on 10m bars, but does not check the scan output TTL beyond the candidate expiry in the SQLite store. If the CSV is stale but the store is not cleaned, intents could still fire.

### Operational & config
- **Hardcoded paths**: `run_daily_scan.sh` hardcodes a local path and assumes venv layout; this is brittle for deployments.
- **Config mutability**: `run_scan.py` mutates global config values (e.g., weekend mode sector limits) which can leak into other runs in the same process.
- **Alert visibility**: Slack alerts are optional and gated on env vars; without them, scan failures and execution errors can be silent.

---

## Potential improvements (post-implementation)

1. **Unify scanning logic**
   - Merge `scanner.py` and the inline scan logic in `run_scan.py` into a single shared module with explicit diagnostics and consistent scoring.
2. **Improve error observability**
   - Replace bare `except` blocks with structured logging + counters to surface data errors.
3. **Harden cache consistency**
   - Include cache metadata (as-of timestamps, source, last refresh) and emit warnings on stale OHLCV or earnings cache.
4. **Formalize execution engine choice**
   - Introduce a single entrypoint/env toggle to choose v1 or v2 and deprecate the unused path.
5. **Strengthen runtime safety**
   - Add max-order-per-day enforcement in v2 (v1 has this), and ensure cross-process locking to prevent parallel submission.
6. **Operational portability**
   - Replace hardcoded path in `run_daily_scan.sh` with a relative repo path or env var.
7. **Schema documentation**
   - Document the `daily_candidates.csv` schema and update it with explicit versioning to match `SchemaVersion`.
8. **Testing & replay**
   - Add unit tests for gate logic (e.g., anchors, ATR filters) and a replay harness for backtesting deterministic runs.

---

## Suggested next steps for implementation planning
- Decide which execution path (v1 or v2) is authoritative and map remaining gaps for that path.
- Add explicit service health checks (scan freshness, candidate count, data feed status) and surface them in Slack.
- Add a README section that describes the end-to-end run command and required env variables.

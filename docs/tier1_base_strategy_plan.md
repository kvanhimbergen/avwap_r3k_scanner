# Tier 1: Base Strategy Extraction + Registry

## Summary

Extracted `BaseRAECStrategy` base class and `StrategyConfig` dataclass from V3/V4/V5
strategy modules, reducing ~2,680 lines across 3 files to ~360 lines (plus ~1,030 lines
of shared base class code).

## What was created

### `strategies/raec_401k_base.py` (~1,030 lines)
- `StrategyConfig` dataclass — all numeric/string params for a strategy
- `RegimeSignal`, `SymbolFeature`, `RunResult` dataclasses
- `BaseRAECStrategy` class with all shared logic:
  - State persistence (`_state_path`, `_load_state`, `_save_state`)
  - Ledger writing (`_write_raec_ledger`)
  - Date/rounding helpers
  - Cash/universe helpers
  - Series/feature computation
  - Ranking/weighting (inverse vol, weight cap, correlation)
  - Portfolio vol estimation
  - Regime target computation (risk-on, transition, risk-off)
  - Drift/rebalance logic
  - Turnover cap + intent building
  - Ticket formatting
  - `run_strategy()` template method
  - CLI helpers (`parse_args`, `main`)

### `strategies/raec_401k_registry.py` (~28 lines)
- `register(strategy)` — add to global registry
- `get(strategy_id)` — lookup by ID
- `all_strategies()` — get all registered
- `registered_ids()` — list registered IDs

### Modified files

**`strategies/raec_401k_v3.py`** (~106 lines, was ~890)
- `StrategyConfig` with V3-specific params
- `register(BaseRAECStrategy(_CONFIG))` at module level
- Module-level backward-compat shims (constants + functions)

**`strategies/raec_401k_v4.py`** (~106 lines, was ~890)
- Same pattern as V3 with V4-specific params

**`strategies/raec_401k_v5.py`** (~198 lines, was ~900)
- `V5Strategy(BaseRAECStrategy)` subclass with overrides:
  - `compute_anchor_signal` — dual VTI+QQQ anchor
  - `_format_signal_block` — includes QQQ signals
  - `_extra_state_fields` — QQQ state fields
  - `_extra_ledger_signals` — QQQ ledger fields
- Module-level backward-compat shims

## Key design decisions

1. **StrategyConfig dataclass** — all numeric tuning knobs in one place
2. **Hook pattern** — `compute_anchor_signal`, `_format_signal_block`, `_extra_state_fields`,
   `_extra_ledger_signals` are overridable hooks for subclass customization
3. **Registry** — auto-discovery via `register()` at module import time
4. **Backward-compat shims** — module-level constants and function aliases so existing
   consumers (backtests, coordinator, allocs) continue working unchanged
5. **V5 subclass** — only strategy needing subclass (dual anchor); V3/V4 use base directly

## Net impact
- **Before**: ~2,680 lines across V3+V4+V5
- **After**: ~1,030 base + ~360 across V3+V4+V5 = ~1,390 total
- **Savings**: ~1,290 lines of duplication eliminated
- **New strategy**: ~30 lines of StrategyConfig + optional hook overrides

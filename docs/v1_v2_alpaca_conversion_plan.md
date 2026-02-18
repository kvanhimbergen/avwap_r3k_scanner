# Convert RAEC V1/V2 from Schwab Manual to Alpaca Paper Trading

## Context

V1 (`strategies/raec_401k.py`, 592 lines) and V2 (`strategies/raec_401k_v2.py`, 866 lines) are intended to be automated paper-trade strategies via Alpaca, layered with AVWAP swing trades. They're currently incorrectly wired as `SCHWAB_401K_MANUAL` (Slack tickets) — same as V3/V4/V5. This conversion creates a clear architectural separation:

- **Automated strategies (Alpaca)**: V1, V2 — paper trading via Alpaca API
- **Manual 401k strategies (Schwab)**: V3, V4, V5 + Coordinator — Slack tickets, fill reporting via web interface

## Key Interface Difference

| Aspect | Current (Schwab Manual) | Target (Alpaca Paper) |
|--------|------------------------|----------------------|
| Adapter | `SchwabManualAdapter` | New `AlpacaRebalanceAdapter` |
| Output | Slack messages | Actual Alpaca orders |
| Units | Percentage allocations | Share quantities |
| Position Source | State JSON / CSV drop | Alpaca API (`get_all_positions`) |
| Fill Tracking | Web interface | Automatic (API polling) |

---

## Phase 1: New Adapter

### New: `execution_v2/alpaca_rebalance_adapter.py`

Create a thin adapter wrapping Alpaca's `TradingClient` for portfolio rebalancing:

- `AlpacaRebalanceAdapter(trading_client, book_id)` class
- `get_account_equity()` → float
- `get_current_allocations(cash_symbol)` → dict[str, float] (percentages from Alpaca positions)
- `execute_rebalance(intents, *, ny_date, repo_root, strategy_id, cash_symbol)` → `RebalanceOrderResult`
- `send_summary_ticket(intents, *, message, ny_date, repo_root, ...)` → `RebalanceOrderResult` (compatibility shim)

Key design:
- Exposes `send_summary_ticket()` with the **same call signature** as `SchwabManualAdapter`, so V1/V2 strategy logic needs minimal changes
- Returns `RebalanceOrderResult` with `.sent` attribute (matches `ManualTicketResult` interface)
- Converts percentage-delta intents → dollar amounts → share quantities: `floor(equity * delta_pct / price)`
- Executes SELLs before BUYs (free cash first)
- Skips cash symbol (BIL) intents — Alpaca cash is the residual
- Records orders via existing `alpaca_paper.build_order_event()` + `alpaca_paper.append_events()`
- Uses `ref_price` field from intents (from strategy's price provider) to avoid new Alpaca market data dependency

Strategies instantiate the adapter themselves (not via `book_router`):
```python
trading_client = book_router.select_trading_client(BOOK_ID)  # returns TradingClient
adapter = AlpacaRebalanceAdapter(trading_client)
result = adapter.send_summary_ticket(intents, ...)
```

### New: `tests/test_alpaca_rebalance_adapter.py`

- `FakeTradingClient` / `FakeAccount` / `FakePosition` / `FakeOrder` mocks
- Tests: allocation percentage computation, sell-before-buy ordering, cash symbol skipping, ledger recording, error handling, `send_summary_ticket` compatibility

### Verification
```bash
./venv/bin/pytest tests/test_alpaca_rebalance_adapter.py -x -v
```

---

## Phase 2: V1 Conversion

### Modify: `strategies/raec_401k.py`

1. `BOOK_ID` → `book_ids.ALPACA_PAPER`
2. Remove `from execution_v2.schwab_manual_adapter import slack_post_enabled`
3. Remove `_load_latest_csv_allocations()` (CSV sync is Schwab-specific)
4. Add `_load_alpaca_allocations(adapter, cash_symbol, universe)` helper
5. In `run_strategy()`:
   - Instantiate `AlpacaRebalanceAdapter` from `book_router.select_trading_client(BOOK_ID)` (or use `adapter_override`)
   - When not `dry_run`: fetch current allocations from Alpaca API instead of state/CSV
   - Add `ref_price` to each intent (from price provider data)
   - Replace `slack_post_enabled()` with env-var check (`ALPACA_REBALANCE_ENABLED`)
   - Execution block: adapter interface is compatible, minimal change
6. `main()` output prefix: `"ALPACA_PAPER: "` instead of `"SCHWAB_401K_MANUAL: "`
7. State path auto-updates: `state/strategies/ALPACA_PAPER/RAEC_401K_V1.json`

### Modify: `tests/test_raec_401k.py`

- `test_intent_id_deterministic`: Update expected hash (BOOK_ID changed)
- CSV allocation test: Remove or rewrite for Alpaca position loading
- Adapter mocks: Swap `_Adapter` for `FakeTradingClient` + `AlpacaRebalanceAdapter`
- State paths in fixtures auto-resolve via `raec_401k.BOOK_ID`

### Verification
```bash
./venv/bin/pytest tests/test_raec_401k.py -x -v
```

---

## Phase 3: V2 Conversion

### Modify: `strategies/raec_401k_v2.py`

Same pattern as V1. Additional notes:
- V2 has a local `SymbolFeature` (no `mom_3m`) — unchanged
- V2's `_rank_symbols` checks `mom_6m` for positive momentum — unchanged
- V2's dynamic targets (momentum scoring, vol targeting) — all unchanged

### Modify: `tests/test_raec_401k_v2.py`

Same pattern as V1 test updates.

### Verification
```bash
./venv/bin/pytest tests/test_raec_401k_v2.py -x -v
```

---

## Phase 4: Cleanup

### Modify: `strategies/raec_401k_allocs.py`

- Remove `"v1"` and `"v2"` from `_STRATEGY_MODULES` (positions now come from Alpaca, not state JSON)
- Change `DEFAULT_STRATEGY_KEY` from `"v1"` to `"v3"` (or `"coord"`)
- Update `DEFAULT_BOOK_ID` to use coordinator's book_id
- Update `DEFAULT_UNIVERSE` to exclude V1/V2 universes

### Full Verification
```bash
./venv/bin/pytest tests/ --ignore=tests/analytics_platform -x -v
```

---

## Cash Symbol (BIL) Handling

- Alpaca holds USD cash, not BIL
- Adapter maps Alpaca's cash balance → strategy's `cash_symbol` in allocation dict
- BIL intents are skipped during order submission (cash is the residual after all trades)
- If BIL is physically held in Alpaca (from prior buys), it appears as a position

## Ledger Organization

After conversion, V1/V2 write to two ledger locations:
1. `ledger/RAEC_REBALANCE/RAEC_401K_V1/{date}.jsonl` — decision records (unchanged)
2. `ledger/ALPACA_PAPER/{date}.jsonl` — order execution events (shared with S1 AVWAP trades, distinguished by `strategy_id` field)

## Not In Scope (Follow-up)

- Integrating V1/V2 into `ops/post_scan_pipeline.py` or `execution_main.py`
- AVWAP signal layering onto V1/V2 targets
- Live trading mode (`ALPACA_LIVE`)

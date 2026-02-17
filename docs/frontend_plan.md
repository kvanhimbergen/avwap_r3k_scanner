# Institutional Analytics Platform — Build Plan

## Architecture Overview

### Current Stack
- **Backend**: FastAPI (Python) — `analytics_platform/backend/app.py`
- **Database**: DuckDB — `analytics_platform/data/analytics.duckdb`
- **Data Pipeline**: `build_readmodels.py` ingests JSONL ledger files into DuckDB tables
- **Frontend**: React 18 + TypeScript + Recharts + react-router-dom v6
- **Build**: Vite + vitest
- **Styling**: Custom CSS (no framework) — `styles.css`

### Current Coverage
The platform currently covers **S1_AVWAP_CORE** and **S2_LETF_ORB_AGGRO** strategies only.

**Missing**: All RAEC 401(k) strategies (V1-V5 + Coordinator) have no analytics presence — no ledger ingestion, no DuckDB tables, no API endpoints, no frontend pages.

### What We're Adding
1. **RAEC ledger emission** — Strategies write structured JSONL records
2. **New DuckDB readmodel tables** — `raec_rebalance_events`, `raec_allocations`, `raec_intents`, `raec_coordinator_runs`
3. **New API endpoints** — P&L, trade journal, RAEC dashboard, readiness
4. **New frontend pages** — P&L, Trade Journal, RAEC Dashboard, Readiness
5. **Sidebar and overview upgrades** — Strategy groups, all-strategy comparison

---

## Strategy Inventory

| ID | Book | Universe Size | Vol Target | Max Weight | Rebalance |
|----|------|--------------|------------|------------|-----------|
| `S1_AVWAP_CORE` | `ALPACA_PAPER/LIVE` | ~20 US equities | N/A | N/A | Intraday |
| `S2_LETF_ORB_AGGRO` | `SCHWAB_401K_MANUAL` | 60 (LETFs + equities) | N/A | N/A | Daily |
| `RAEC_401K_V1` | `SCHWAB_401K_MANUAL` | 7 (VTI, SPY, QUAL...) | 12% | 45% | Monthly |
| `RAEC_401K_V2` | `SCHWAB_401K_MANUAL` | 14 (QQQ, VTI, GLD...) | 12% | 45% | Monthly |
| `RAEC_401K_V3` | `SCHWAB_401K_MANUAL` | 17 (TQQQ, SOXL, TECL...) | 18% | 60% | Daily |
| `RAEC_401K_V4` | `SCHWAB_401K_MANUAL` | 19 (XLE, ERX, VNQ...) | 14% | 40% | Daily |
| `RAEC_401K_V5` | `SCHWAB_401K_MANUAL` | 21 (SOXL, TECL, NVDA...) | 22% | 70% | Daily |
| `RAEC_401K_COORD` | `SCHWAB_401K_MANUAL` | Union V3+V4+V5 | N/A | N/A | Daily |

---

## Phase 1: Data Pipeline — RAEC Ledger Emission & Ingestion

### Task 1.1: Define RAEC Ledger Record Schema

Create a standardized JSONL record emitted by each RAEC strategy after `run_strategy()` completes.

**Ledger path**: `ledger/RAEC_REBALANCE/{STRATEGY_ID}/{YYYY-MM-DD}.jsonl`

**Record schema**:
```json
{
  "record_type": "RAEC_REBALANCE_EVENT",
  "ts_utc": "2026-02-17T14:30:00+00:00",
  "ny_date": "2026-02-17",
  "book_id": "SCHWAB_401K_MANUAL",
  "strategy_id": "RAEC_401K_V3",
  "regime": "RISK_ON",
  "should_rebalance": true,
  "rebalance_trigger": "daily",
  "targets": {"TQQQ": 35.0, "SOXL": 25.0, "BIL": 40.0},
  "current_allocations": {"SPY": 50.0, "BIL": 50.0},
  "intent_count": 3,
  "intents": [
    {
      "intent_id": "abc123...",
      "symbol": "TQQQ",
      "side": "BUY",
      "delta_pct": 35.0,
      "target_pct": 35.0,
      "current_pct": 0.0
    }
  ],
  "signals": {
    "sma200": 180.5,
    "sma50": 195.3,
    "vol20": 0.185,
    "vol252": 0.162,
    "dd63_pct": -2.3,
    "anchor_symbol": "VTI"
  },
  "momentum_scores": [
    {"symbol": "TQQQ", "score": 2.45, "ret_6m": 0.152},
    {"symbol": "SOXL", "score": 1.98, "ret_6m": 0.121}
  ],
  "portfolio_vol_target": 0.18,
  "portfolio_vol_realized": 0.165,
  "posted": true,
  "notice": null,
  "build_git_sha": "abc123"
}
```

**Coordinator record** (additional fields):
```json
{
  "record_type": "RAEC_COORDINATOR_RUN",
  "capital_split": {"v3": 0.40, "v4": 0.30, "v5": 0.30},
  "sub_strategy_results": {
    "v3": {"regime": "RISK_ON", "should_rebalance": true, "intent_count": 2},
    "v4": {"regime": "TRANSITION", "should_rebalance": false, "intent_count": 0},
    "v5": {"regime": "RISK_ON", "should_rebalance": true, "intent_count": 1}
  }
}
```

### Task 1.2: Add Ledger Writer to RAEC Strategies

Add `_write_ledger()` to each strategy's `run_strategy()` function. Write after state save, before return.

**Files modified**:
- `strategies/raec_401k.py` (V1)
- `strategies/raec_401k_v2.py` (V2)
- `strategies/raec_401k_v3.py` (V3)
- `strategies/raec_401k_v4.py` (V4)
- `strategies/raec_401k_v5.py` (V5)
- `strategies/raec_401k_coordinator.py` (Coordinator)

**Pattern**: Use `_iter_jsonl` / append pattern from `schwab_manual_adapter.py`.

### Task 1.3: Add RAEC Ingestion to build_readmodels.py

Extend `build_readmodels()` to scan `ledger/RAEC_REBALANCE/*/**.jsonl` and populate new DuckDB tables.

**New DuckDB tables**:

#### `raec_rebalance_events`
| Column | Type | Description |
|--------|------|-------------|
| `event_id` | VARCHAR | SHA hash of record |
| `ny_date` | VARCHAR | Trade date |
| `ts_utc` | VARCHAR | Timestamp |
| `strategy_id` | VARCHAR | RAEC_401K_V1..V5 |
| `book_id` | VARCHAR | SCHWAB_401K_MANUAL |
| `regime` | VARCHAR | RISK_ON / TRANSITION / RISK_OFF |
| `should_rebalance` | BOOLEAN | Whether rebalance triggered |
| `rebalance_trigger` | VARCHAR | daily / monthly / drift / regime_change |
| `intent_count` | INTEGER | Number of trade intents |
| `portfolio_vol_target` | DOUBLE | Target volatility |
| `portfolio_vol_realized` | DOUBLE | Realized volatility |
| `posted` | BOOLEAN | Slack ticket posted |
| `notice` | VARCHAR | Error/info message |
| `signals_json` | VARCHAR | JSON of signal values |
| `momentum_json` | VARCHAR | JSON of momentum scores |
| `targets_json` | VARCHAR | JSON of target allocations |
| `current_json` | VARCHAR | JSON of current allocations |
| `source_file` | VARCHAR | Source JSONL path |

#### `raec_allocations`
| Column | Type | Description |
|--------|------|-------------|
| `ny_date` | VARCHAR | Date |
| `strategy_id` | VARCHAR | Strategy |
| `alloc_type` | VARCHAR | "target" or "current" |
| `symbol` | VARCHAR | Ticker |
| `weight_pct` | DOUBLE | Allocation percentage |

#### `raec_intents`
| Column | Type | Description |
|--------|------|-------------|
| `ny_date` | VARCHAR | Date |
| `ts_utc` | VARCHAR | Timestamp |
| `strategy_id` | VARCHAR | Strategy |
| `intent_id` | VARCHAR | Unique intent hash |
| `symbol` | VARCHAR | Ticker |
| `side` | VARCHAR | BUY / SELL |
| `delta_pct` | DOUBLE | Change amount |
| `target_pct` | DOUBLE | Target allocation |
| `current_pct` | DOUBLE | Current allocation |

#### `raec_coordinator_runs`
| Column | Type | Description |
|--------|------|-------------|
| `ny_date` | VARCHAR | Date |
| `ts_utc` | VARCHAR | Timestamp |
| `capital_split_json` | VARCHAR | JSON of capital split |
| `sub_results_json` | VARCHAR | JSON of sub-strategy summaries |

**New freshness sources** (add to `sources` list):
```python
SourceHealth(
    source_name="raec_rebalance_events",
    source_glob=str(settings.ledger_dir / "RAEC_REBALANCE" / "**" / "*.jsonl"),
)
```

### Task 1.4: Add Tests for RAEC Ingestion

Add test fixtures and tests for the new readmodel tables.

**File**: `tests/analytics_platform/test_readmodels_raec.py`

**Test cases**:
- `test_raec_rebalance_event_ingestion` — single event populates all 4 tables
- `test_raec_coordinator_run_ingestion` — coordinator record creates coordinator row
- `test_raec_allocations_target_and_current` — both target and current rows created
- `test_raec_intents_parsed` — intents unpacked correctly
- `test_raec_idempotent` — running twice produces same result
- `test_raec_freshness_source_added` — freshness_health includes raec source

---

## Phase 2: Backend API — New Endpoints

### Task 2.1: RAEC Dashboard Endpoint

**Route**: `GET /api/v1/raec/dashboard`

**Query params**: `start`, `end`, `strategy_id` (optional, filters to one strategy)

**Response** (`data` field):
```json
{
  "summary": {
    "total_rebalance_events": 45,
    "rebalances_triggered": 30,
    "by_strategy": [
      {
        "strategy_id": "RAEC_401K_V3",
        "events": 15,
        "rebalances": 10,
        "current_regime": "RISK_ON",
        "last_eval_date": "2026-02-17",
        "portfolio_vol_target": 0.18
      }
    ]
  },
  "regime_history": [
    {"ny_date": "2026-02-17", "strategy_id": "RAEC_401K_V3", "regime": "RISK_ON"}
  ],
  "allocation_snapshots": [
    {"ny_date": "2026-02-17", "strategy_id": "RAEC_401K_V3", "symbol": "TQQQ", "weight_pct": 35.0, "alloc_type": "target"}
  ]
}
```

**Query function**: `queries.get_raec_dashboard(conn, start, end, strategy_id)`

### Task 2.2: Trade Journal Endpoint

**Route**: `GET /api/v1/journal`

**Query params**: `start`, `end`, `strategy_id`, `symbol`, `side`, `limit`

**Response** (`data` field):
```json
{
  "count": 42,
  "rows": [
    {
      "ny_date": "2026-02-17",
      "ts_utc": "2026-02-17T14:30:00+00:00",
      "strategy_id": "RAEC_401K_V3",
      "intent_id": "abc123...",
      "symbol": "TQQQ",
      "side": "BUY",
      "delta_pct": 35.0,
      "target_pct": 35.0,
      "current_pct": 0.0,
      "regime": "RISK_ON",
      "posted": true
    }
  ]
}
```

**Data source**: Join `raec_intents` with `raec_rebalance_events` for regime context. Also union with `decision_intents` for S1/S2 trades.

### Task 2.3: RAEC Readiness Endpoint

**Route**: `GET /api/v1/raec/readiness`

**Response** (`data` field):
```json
{
  "strategies": [
    {
      "strategy_id": "RAEC_401K_V3",
      "state_file_exists": true,
      "last_eval_date": "2026-02-17",
      "last_regime": "RISK_ON",
      "has_allocations": true,
      "allocation_count": 3,
      "total_weight_pct": 100.0,
      "ledger_files_today": 1,
      "warnings": []
    }
  ],
  "coordinator": {
    "state_file_exists": true,
    "capital_split": {"v3": 0.40, "v4": 0.30, "v5": 0.30},
    "sub_strategies_ready": 3,
    "warnings": []
  }
}
```

**Data source**: Read state files directly from `state/strategies/SCHWAB_401K_MANUAL/*.json` + check ledger dir.

### Task 2.4: Strategy Comparison Upgrade

Extend existing `GET /api/v1/strategies/compare` to include RAEC strategies alongside S1/S2.

**Additional fields in response**:
```json
{
  "raec_compare": [
    {
      "strategy_id": "RAEC_401K_V3",
      "total_rebalances": 30,
      "total_intents": 45,
      "unique_symbols": 8,
      "current_regime": "RISK_ON",
      "last_eval": "2026-02-17"
    }
  ]
}
```

### Task 2.5: P&L Tracking Endpoint

**Route**: `GET /api/v1/pnl`

**Query params**: `start`, `end`, `strategy_id`

**Response** (`data` field):
```json
{
  "by_strategy": [
    {
      "strategy_id": "RAEC_401K_V3",
      "allocation_drift_series": [
        {"ny_date": "2026-02-17", "total_drift_pct": 3.2}
      ],
      "regime_changes": 5,
      "rebalance_count": 30
    }
  ]
}
```

**Note**: True P&L requires price data. Phase 1 tracks allocation drift and rebalance frequency as proxies. Real P&L requires integrating with `data.prices` module in a future phase.

### Task 2.6: Add RAEC Export Datasets

Extend `EXPORT_TABLES` in `queries.py`:
```python
EXPORT_TABLES = {
    # ... existing ...
    "raec_rebalance_events": ("raec_rebalance_events", "ny_date"),
    "raec_allocations": ("raec_allocations", "ny_date"),
    "raec_intents": ("raec_intents", "ny_date"),
    "raec_coordinator_runs": ("raec_coordinator_runs", "ny_date"),
}
```

### Task 2.7: API Tests

**File**: `tests/analytics_platform/test_api_raec.py`

**Test cases**:
- `test_raec_dashboard_returns_summary` — endpoint returns valid envelope
- `test_raec_dashboard_filter_by_strategy` — strategy_id filter works
- `test_journal_returns_intents` — journal endpoint returns trade rows
- `test_journal_filter_by_symbol` — symbol filter works
- `test_readiness_all_strategies` — readiness shows all 6 RAEC strategies
- `test_pnl_drift_series` — P&L endpoint returns drift data
- `test_raec_exports` — CSV export works for new tables
- `test_strategies_compare_includes_raec` — compare endpoint includes raec_compare

---

## Phase 3: Frontend — New Pages

### Task 3.1: Add API Client Methods

Extend `api.ts` with new methods:

```typescript
raecDashboard: (args?: { start?: string; end?: string; strategy_id?: string }) =>
  get<KeyValue>(`/api/v1/raec/dashboard${toQuery(args ?? {})}`),

journal: (args?: { start?: string; end?: string; strategy_id?: string; symbol?: string; side?: string; limit?: number }) =>
  get<KeyValue>(`/api/v1/journal${toQuery(args ?? {})}`),

raecReadiness: () =>
  get<KeyValue>("/api/v1/raec/readiness"),

pnl: (args?: { start?: string; end?: string; strategy_id?: string }) =>
  get<KeyValue>(`/api/v1/pnl${toQuery(args ?? {})}`),
```

### Task 3.2: RAEC Dashboard Page

**File**: `analytics_platform/frontend/src/pages/RaecDashboardPage.tsx`

**Layout**:
1. **Strategy selector** — dropdown/tabs for V1-V5 + Coordinator + All
2. **KPI row** — Total Rebalances, Current Regime, Portfolio Vol Target, Last Eval
3. **Regime timeline chart** — Recharts Line/Area showing regime transitions over time
4. **Allocation pie/bar** — Current target allocations per strategy (bar chart, one bar per symbol)
5. **Rebalance history table** — Date, Strategy, Regime, Trigger, Intent Count, Posted

**Data fetching**: `usePolling(() => api.raecDashboard({strategy_id}), 45_000)`

**Patterns to follow**: Same as `OverviewPage.tsx` — usePolling, LoadingState, ErrorState, KpiCard, chart-card divs.

### Task 3.3: Trade Journal Page

**File**: `analytics_platform/frontend/src/pages/JournalPage.tsx`

**Layout**:
1. **Filter bar** — Date range, Strategy dropdown (All/S1/S2/RAEC V1-V5), Symbol search, Side (All/BUY/SELL)
2. **Summary KPIs** — Total Trades, Buys, Sells, Unique Symbols
3. **Trade table** — Sortable: Date, Strategy, Symbol, Side, Delta%, Target%, Current%, Regime, Posted
4. **Export button** — Links to CSV export

**Data fetching**: `usePolling(() => api.journal({start, end, strategy_id, symbol, side}), 45_000)`

### Task 3.4: RAEC Readiness Page

**File**: `analytics_platform/frontend/src/pages/ReadinessPage.tsx`

**Layout**:
1. **Overall status banner** — Green/Yellow/Red based on warnings count
2. **Strategy cards grid** — One card per RAEC strategy showing:
   - State file status (exists/missing)
   - Last eval date + staleness warning
   - Current regime
   - Allocation count + total weight
   - Ledger files today count
   - Warning list
3. **Coordinator card** — Capital split, sub-strategy readiness count

**Data fetching**: `usePolling(() => api.raecReadiness(), 60_000)`

### Task 3.5: P&L Page

**File**: `analytics_platform/frontend/src/pages/PnlPage.tsx`

**Layout**:
1. **Strategy selector** — dropdown for strategy_id filter
2. **KPI row** — Rebalance Count, Regime Changes, Avg Drift
3. **Drift chart** — Line chart showing allocation drift over time per strategy
4. **Rebalance frequency chart** — Bar chart of rebalance counts by week/month

**Data fetching**: `usePolling(() => api.pnl({strategy_id}), 45_000)`

### Task 3.6: Add TypeScript Types

Extend `types.ts` with interfaces for new API responses:

```typescript
export interface RaecRebalanceEvent {
  ny_date: string;
  strategy_id: string;
  regime: string;
  should_rebalance: boolean;
  rebalance_trigger: string;
  intent_count: number;
  portfolio_vol_target: number;
  posted: boolean;
}

export interface JournalRow {
  ny_date: string;
  ts_utc: string;
  strategy_id: string;
  intent_id: string;
  symbol: string;
  side: string;
  delta_pct: number;
  target_pct: number;
  current_pct: number;
  regime: string;
  posted: boolean;
}

export interface ReadinessStrategy {
  strategy_id: string;
  state_file_exists: boolean;
  last_eval_date: string | null;
  last_regime: string | null;
  has_allocations: boolean;
  allocation_count: number;
  total_weight_pct: number;
  ledger_files_today: number;
  warnings: string[];
}
```

---

## Phase 4: Integration — Sidebar, Overview, Comparison

### Task 4.1: Sidebar Reorganization

Update `Layout.tsx` `NAV_ITEMS` to group pages:

```typescript
const NAV_SECTIONS = [
  {
    label: "Operations",
    items: [
      { to: "/", label: "Overview" },
      { to: "/decisions", label: "Decisions" },
      { to: "/risk", label: "Risk" },
    ],
  },
  {
    label: "AVWAP + S2",
    items: [
      { to: "/strategies", label: "Strategies" },
      { to: "/signals/s2", label: "S2 Signals" },
    ],
  },
  {
    label: "RAEC 401(k)",
    items: [
      { to: "/raec", label: "Dashboard" },
      { to: "/raec/readiness", label: "Readiness" },
    ],
  },
  {
    label: "Analysis",
    items: [
      { to: "/journal", label: "Trade Journal" },
      { to: "/pnl", label: "P&L" },
      { to: "/backtests", label: "Backtests" },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/help", label: "Help" },
    ],
  },
];
```

### Task 4.2: Overview Page Upgrade

Add RAEC summary section to OverviewPage:

1. Fetch `api.raecDashboard()` in addition to existing overview data
2. Add new KPI cards: "RAEC Strategies Active", "Current Regimes", "Rebalances Today"
3. Add regime summary — one line per RAEC strategy showing current regime

### Task 4.3: Route Registration

Update `App.tsx` with new routes:

```typescript
<Route path="/raec" element={<RaecDashboardPage />} />
<Route path="/raec/readiness" element={<ReadinessPage />} />
<Route path="/journal" element={<JournalPage />} />
<Route path="/pnl" element={<PnlPage />} />
```

### Task 4.4: Help Page Update

Add new pages to the Help page's "Page-by-Page Purpose" table:

| Page | Use It For | When To Act |
|------|-----------|-------------|
| RAEC Dashboard | Regime status, allocation targets, rebalance history for 401(k) | Act if regime changes unexpectedly or rebalances stop |
| Readiness | Pre-market check that all RAEC strategies have valid state | Act if any strategy shows warnings or stale eval dates |
| Trade Journal | Unified trade log across all strategies | Review weekly for pattern analysis |
| P&L | Allocation drift tracking and rebalance frequency | Act if drift exceeds thresholds consistently |

### Task 4.5: Frontend Tests

**File**: `analytics_platform/frontend/src/__tests__/raec_pages.test.tsx`

Test that new pages render without crashing (smoke tests using `@testing-library/react`).

### Task 4.6: Styles for New Components

Add CSS rules to `styles.css` for:
- Strategy selector dropdowns (`.strategy-selector`)
- Regime badge colors (`.regime-badge.risk-on`, `.regime-badge.transition`, `.regime-badge.risk-off`)
- Readiness status cards (`.readiness-card`, `.readiness-ok`, `.readiness-warn`, `.readiness-error`)
- Filter bar layout (`.filter-bar`)
- Trade journal table (`.journal-table`)

---

## Data Flow Summary

```
RAEC Strategies (V1-V5)          S1/S2 Strategies
         │                              │
         ▼                              ▼
  run_strategy()                 execution_v2/
         │                              │
         ▼                              ▼
  ledger/RAEC_REBALANCE/         ledger/PORTFOLIO_DECISIONS/
  {STRATEGY_ID}/                 ledger/STRATEGY_SIGNALS/
  {date}.jsonl                   {date}.jsonl
         │                              │
         └──────────┬───────────────────┘
                    ▼
           build_readmodels()
                    │
                    ▼
              DuckDB Tables
         ┌──────────┼──────────────┐
         ▼          ▼              ▼
  raec_rebalance  decision_    strategy_
  _events         cycles       signals
  raec_intents    decision_    risk_controls
  raec_allocs     intents      _daily
  raec_coord      gate_blocks  regime_daily
                    │
                    ▼
              FastAPI Endpoints
         ┌──────────┼──────────────┐
         ▼          ▼              ▼
  /api/v1/raec/   /api/v1/     /api/v1/
  dashboard       overview     signals/s2
  /api/v1/raec/   /api/v1/     /api/v1/
  readiness       journal      risk/
  /api/v1/pnl                  controls
                    │
                    ▼
           React Frontend
  ┌─────────────────┼───────────────────┐
  ▼                 ▼                   ▼
  RaecDashboard   JournalPage      OverviewPage
  ReadinessPage   PnlPage          (upgraded)
```

---

## Dependency Order

```
Task 1.1 (Schema)
  └→ Task 1.2 (Ledger Writer)    ← can run with 1.1
  └→ Task 1.3 (Ingestion)        ← depends on 1.1
     └→ Task 1.4 (Tests)         ← depends on 1.3
        └→ Task 2.1-2.6 (API)    ← depends on 1.3
           └→ Task 2.7 (API Tests)  ← depends on 2.1-2.6
              └→ Task 3.1 (API Client)  ← depends on 2.1-2.6
                 └→ Task 3.2-3.5 (Pages)  ← can run in parallel
                    └→ Task 3.6 (Types)  ← can run with 3.2-3.5
                       └→ Task 4.1-4.6 (Integration)  ← depends on 3.x
```

---

## File Inventory

### New Files
| File | Phase | Purpose |
|------|-------|---------|
| `tests/analytics_platform/test_readmodels_raec.py` | 1 | Readmodel ingestion tests |
| `tests/analytics_platform/test_api_raec.py` | 2 | API endpoint tests |
| `frontend/src/pages/RaecDashboardPage.tsx` | 3 | RAEC dashboard |
| `frontend/src/pages/JournalPage.tsx` | 3 | Trade journal |
| `frontend/src/pages/ReadinessPage.tsx` | 3 | RAEC readiness |
| `frontend/src/pages/PnlPage.tsx` | 3 | P&L tracking |
| `frontend/src/__tests__/raec_pages.test.tsx` | 4 | Frontend smoke tests |

### Modified Files
| File | Phase | Changes |
|------|-------|---------|
| `strategies/raec_401k.py` | 1 | Add `_write_ledger()` |
| `strategies/raec_401k_v2.py` | 1 | Add `_write_ledger()` |
| `strategies/raec_401k_v3.py` | 1 | Add `_write_ledger()` |
| `strategies/raec_401k_v4.py` | 1 | Add `_write_ledger()` |
| `strategies/raec_401k_v5.py` | 1 | Add `_write_ledger()` |
| `strategies/raec_401k_coordinator.py` | 1 | Add `_write_ledger()` |
| `backend/readmodels/build_readmodels.py` | 1, 5 | Add RAEC ingestion + analytics ingestion |
| `backend/api/queries.py` | 2, 5, 6 | Add RAEC, analytics, portfolio query functions |
| `backend/app.py` | 2, 5, 6 | Add new endpoints |
| `frontend/src/api.ts` | 3, 5, 6 | Add API client methods |
| `frontend/src/types.ts` | 3, 5, 6 | Add TypeScript interfaces |
| `frontend/src/App.tsx` | 4, 5, 6 | Add routes |
| `frontend/src/components/Layout.tsx` | 4, 6 | Sidebar sections |
| `frontend/src/pages/OverviewPage.tsx` | 4, 6 | RAEC + portfolio summary |
| `frontend/src/pages/HelpPage.tsx` | 4, 6 | New page docs |
| `frontend/src/styles.css` | 4, 5, 6 | New component styles |
| `tests/analytics_platform/conftest.py` | 1, 5 | RAEC + analytics fixture data |

---

## Phase 5: S1/S2 Trade Analytics & Execution Quality

### Context

The existing `analytics/` Python module contains a rich data model that is NOT yet surfaced in the analytics platform:
- **Fill** — Individual order fills (fill_id, venue, symbol, side, qty, price, fees, strategy_id)
- **Trade** — Reconstructed round-trip trades (open/close fill, entry/exit price, P&L, strategy_id)
- **Lot** — Open position lots (symbol, remaining_qty, open_price, strategy_id)
- **DailyAggregate** — Per-day metrics (trade_count, realized_pnl, fees, symbols_traded)
- **ExitEvent/ExitTrade** — Trade exits with stop_price, reason, MAE/MFE data
- **SlippageEvent** — Execution quality (expected vs. actual fill, slippage_bps, liquidity_bucket, time_of_day_bucket)
- **PortfolioSnapshot** — End-of-day positions, capital, exposure, P&L

These primarily cover **S1_AVWAP_CORE** and **S2_LETF_ORB_AGGRO** (broker-executed strategies). The existing `ledger/EXECUTION_SLIPPAGE/` directory stores slippage data, and `analytics/artifacts/portfolio_snapshots/` stores daily snapshots.

### Task 5.1: Add Analytics Fixture Data to conftest

Extend `tests/analytics_platform/conftest.py` with fixture JSONL for:
- `ledger/EXECUTION_SLIPPAGE/2026-02-10.jsonl` — 3 SlippageEvent records (different liquidity buckets, time-of-day buckets)
- `ledger/PORTFOLIO_RISK_ATTRIBUTION/2026-02-10.jsonl` — 2 risk attribution records
- `analytics/artifacts/portfolio_snapshots/2026-02-10.json` — 1 PortfolioSnapshot with 3 positions

**SlippageEvent fixture**:
```json
{
  "schema_version": 1,
  "record_type": "EXECUTION_SLIPPAGE",
  "date_ny": "2026-02-10",
  "symbol": "AAPL",
  "strategy_id": "S1_AVWAP_CORE",
  "expected_price": 185.50,
  "ideal_fill_price": 185.45,
  "actual_fill_price": 185.52,
  "slippage_bps": 3.78,
  "adv_shares_20d": 55000000.0,
  "liquidity_bucket": "mega",
  "fill_ts_utc": "2026-02-10T15:30:00+00:00",
  "time_of_day_bucket": "10:30-11:00"
}
```

**PortfolioSnapshot fixture** (`analytics/artifacts/portfolio_snapshots/2026-02-10.json`):
```json
{
  "schema_version": 2,
  "date_ny": "2026-02-10",
  "run_id": "fixture-run-001",
  "strategy_ids": ["S1_AVWAP_CORE", "S2_LETF_ORB_AGGRO"],
  "capital": {"total": 100000.0, "cash": 45000.0, "invested": 55000.0},
  "gross_exposure": 55000.0,
  "net_exposure": 42000.0,
  "positions": [
    {"strategy_id": "S1_AVWAP_CORE", "symbol": "AAPL", "qty": 100, "avg_price": 180.0, "mark_price": 185.50, "notional": 18550.0},
    {"strategy_id": "S1_AVWAP_CORE", "symbol": "MSFT", "qty": 50, "avg_price": 410.0, "mark_price": 420.0, "notional": 21000.0},
    {"strategy_id": "S2_LETF_ORB_AGGRO", "symbol": "TQQQ", "qty": 200, "avg_price": 75.0, "mark_price": 77.25, "notional": 15450.0}
  ],
  "pnl": {"realized_today": 150.0, "unrealized": 2000.0, "fees_today": 2.50},
  "metrics": {},
  "provenance": {"ledger_paths": [], "input_hashes": {}}
}
```

### Task 5.2: Ingest Analytics Data into DuckDB

Extend `build_readmodels.py` to ingest:

#### New DuckDB tables:

##### `execution_slippage`
| Column | Type | Description |
|--------|------|-------------|
| `date_ny` | VARCHAR | Trade date |
| `symbol` | VARCHAR | Ticker |
| `strategy_id` | VARCHAR | S1_AVWAP_CORE / S2_LETF_ORB_AGGRO |
| `expected_price` | DOUBLE | Expected fill price |
| `ideal_fill_price` | DOUBLE | Ideal/benchmark price |
| `actual_fill_price` | DOUBLE | Actual execution price |
| `slippage_bps` | DOUBLE | Slippage in basis points |
| `adv_shares_20d` | DOUBLE | 20-day avg daily volume |
| `liquidity_bucket` | VARCHAR | mega / large / mid / small |
| `fill_ts_utc` | VARCHAR | Fill timestamp UTC |
| `time_of_day_bucket` | VARCHAR | 30-min bucket (09:30-10:00, etc.) |
| `source_file` | VARCHAR | Source JSONL path |

##### `portfolio_snapshots`
| Column | Type | Description |
|--------|------|-------------|
| `date_ny` | VARCHAR | Snapshot date |
| `run_id` | VARCHAR | Snapshot run ID |
| `strategy_ids_json` | VARCHAR | JSON list of strategy IDs |
| `capital_total` | DOUBLE | Total capital |
| `capital_cash` | DOUBLE | Cash |
| `capital_invested` | DOUBLE | Invested |
| `gross_exposure` | DOUBLE | Gross exposure |
| `net_exposure` | DOUBLE | Net exposure |
| `realized_pnl` | DOUBLE | Realized P&L today |
| `unrealized_pnl` | DOUBLE | Unrealized P&L |
| `fees_today` | DOUBLE | Fees today |
| `source_file` | VARCHAR | Source JSON path |

##### `portfolio_positions`
| Column | Type | Description |
|--------|------|-------------|
| `date_ny` | VARCHAR | Snapshot date |
| `strategy_id` | VARCHAR | Strategy |
| `symbol` | VARCHAR | Ticker |
| `qty` | DOUBLE | Position quantity |
| `avg_price` | DOUBLE | Average entry price |
| `mark_price` | DOUBLE | Mark/current price |
| `notional` | DOUBLE | Position notional value |

##### `risk_attribution`
| Column | Type | Description |
|--------|------|-------------|
| `date_ny` | VARCHAR | Date |
| `record_json` | VARCHAR | Full JSON record (flexible schema) |
| `source_file` | VARCHAR | Source JSONL path |

**Ingestion sources**:
- `ledger/EXECUTION_SLIPPAGE/*.jsonl` → `execution_slippage`
- `analytics/artifacts/portfolio_snapshots/*.json` → `portfolio_snapshots` + `portfolio_positions`
- `ledger/PORTFOLIO_RISK_ATTRIBUTION/*.jsonl` → `risk_attribution`

**New freshness sources**:
```python
SourceHealth(source_name="execution_slippage", source_glob=str(settings.ledger_dir / "EXECUTION_SLIPPAGE" / "*.jsonl")),
SourceHealth(source_name="portfolio_snapshots", source_glob=str(settings.repo_root / "analytics" / "artifacts" / "portfolio_snapshots" / "*.json")),
```

### Task 5.3: Readmodel Tests for Analytics Tables

**File**: `tests/analytics_platform/test_readmodels_analytics.py`

**Test cases**:
- `test_slippage_events_ingested` — verify execution_slippage table has rows, check slippage_bps value
- `test_slippage_liquidity_buckets` — verify mega/large/mid/small buckets classified correctly
- `test_portfolio_snapshot_ingested` — verify portfolio_snapshots table has capital, exposure values
- `test_portfolio_positions_ingested` — verify portfolio_positions table has 3 position rows
- `test_risk_attribution_ingested` — verify risk_attribution table has records
- `test_analytics_freshness_sources` — verify freshness_health includes execution_slippage and portfolio_snapshots

### Task 5.4: Execution Quality Query Functions

Add to `queries.py`:

1. `get_slippage_dashboard(conn, start, end, strategy_id=None)`:
   - Summary: mean/median/p95 slippage across all executions
   - By liquidity bucket: mean slippage per bucket (mega/large/mid/small)
   - By time of day: mean slippage per 30-min bucket
   - By symbol: top 10 symbols by absolute slippage
   - Trend: daily average slippage over time

2. `get_trade_analytics(conn, start, end, strategy_id=None)`:
   - Uses `decision_intents` (existing table) for S1/S2 trade data
   - Unions with `raec_intents` for RAEC data
   - Per-strategy: trade count, unique symbols, buy/sell ratio
   - Daily trade frequency chart data
   - Symbol concentration: top symbols by trade count

### Task 5.5: API Endpoints for Execution Quality

**Route**: `GET /api/v1/execution/slippage`
- Query params: `start`, `end`, `strategy_id`
- Returns: slippage summary, by_bucket, by_time, by_symbol, trend

**Route**: `GET /api/v1/analytics/trades`
- Query params: `start`, `end`, `strategy_id`
- Returns: per_strategy summary, daily_frequency, symbol_concentration

### Task 5.6: Slippage Dashboard Page

**File**: `analytics_platform/frontend/src/pages/SlippagePage.tsx`

**Layout**:
1. **Strategy selector** — All / S1_AVWAP_CORE / S2_LETF_ORB_AGGRO
2. **KPI row** — Mean Slippage (bps), Median Slippage, P95 Slippage, Total Executions
3. **By Liquidity Bucket** — Grouped bar chart (mega/large/mid/small) showing mean slippage
4. **By Time of Day** — Bar chart with 30-min buckets showing mean slippage (highlights worst times)
5. **Top Symbols** — Table of top 10 symbols ranked by absolute slippage
6. **Trend chart** — Line chart of daily avg slippage over time

**Data fetching**: `usePolling(() => api.slippage({strategy_id}), 60_000)`

### Task 5.7: Trade Analytics Page

**File**: `analytics_platform/frontend/src/pages/TradeAnalyticsPage.tsx`

**Layout**:
1. **Strategy selector** — All / per strategy
2. **KPI row** — Total Trades, Unique Symbols, Buy/Sell Ratio, Active Strategies
3. **Trade frequency chart** — Line chart of daily trade count over time
4. **Per-strategy breakdown** — Table: Strategy, Trade Count, Unique Symbols, Buy%, Sell%
5. **Symbol concentration** — Horizontal bar chart of top 15 symbols by trade count
6. **Strategy comparison** — Side-by-side metrics for all active strategies

**Data fetching**: `usePolling(() => api.tradeAnalytics({strategy_id}), 45_000)`

### Task 5.8: API Tests for Analytics Endpoints

**File**: `tests/analytics_platform/test_api_analytics.py`

**Test cases**:
- `test_slippage_dashboard` — endpoint returns valid envelope with by_bucket data
- `test_slippage_filter_strategy` — strategy_id filter works
- `test_trade_analytics` — endpoint returns per_strategy and daily_frequency
- `test_analytics_exports` — CSV export works for execution_slippage table

---

## Phase 6: Portfolio-Level Views & Unified Dashboard

### Context

This phase creates cross-strategy portfolio views that unify all 8+ strategies into a single picture. It leverages the `PortfolioSnapshot` data (positions, capital, exposure) and creates the "big picture" views that tie everything together.

### Task 6.1: Portfolio Query Functions

Add to `queries.py`:

1. `get_portfolio_overview(conn, start, end)`:
   - Latest snapshot: total capital, cash, invested, gross/net exposure
   - Position breakdown: all positions grouped by strategy_id with notional values
   - Exposure by strategy: pie chart data (strategy_id → total notional)
   - Capital utilization: cash% vs invested% over time
   - P&L summary: realized_pnl, unrealized_pnl, fees over date range

2. `get_portfolio_positions(conn, date=None)`:
   - All positions from latest snapshot (or specified date)
   - Columns: strategy_id, symbol, qty, avg_price, mark_price, notional, weight_pct (% of total)
   - Grouped by strategy for easy rendering
   - Sort by notional descending

3. `get_portfolio_history(conn, start, end)`:
   - Time series from portfolio_snapshots: date, capital_total, gross_exposure, net_exposure, realized_pnl
   - Used for drawing equity curve and exposure charts

4. `get_cross_strategy_comparison(conn, start, end)`:
   - Per-strategy metrics pulled from multiple tables:
     - S1/S2: trade count from decision_intents, signal count from strategy_signals
     - RAEC: rebalance count from raec_rebalance_events, regime from latest event
   - Symbol overlap matrix: which symbols appear in multiple strategies
   - Combined: strategy_id, trade_count, unique_symbols, latest_regime (if applicable), exposure

### Task 6.2: Portfolio API Endpoints

**Route**: `GET /api/v1/portfolio/overview`
- Returns: capital summary, position breakdown, exposure by strategy, P&L

**Route**: `GET /api/v1/portfolio/positions`
- Query params: `date` (optional, defaults to latest)
- Returns: all positions with strategy attribution and weight

**Route**: `GET /api/v1/portfolio/history`
- Query params: `start`, `end`
- Returns: time series of capital, exposure, P&L

**Route**: `GET /api/v1/strategies/matrix`
- Returns: cross-strategy comparison with symbol overlap

### Task 6.3: Portfolio Overview Page

**File**: `analytics_platform/frontend/src/pages/PortfolioPage.tsx`

**Layout**:
1. **Capital KPI row** — Total Capital, Cash, Invested, Gross Exposure, Net Exposure
2. **P&L KPI row** — Realized P&L (today), Unrealized P&L, Fees (today)
3. **Exposure by Strategy** — Recharts PieChart showing notional per strategy
4. **Capital Over Time** — Line chart of total capital + gross exposure over time
5. **P&L Trend** — Line chart of cumulative realized P&L
6. **Position Summary Table** — All positions grouped by strategy with columns: Symbol, Qty, Avg Price, Mark Price, Notional, Weight%

**Data fetching**: Multiple polls:
```typescript
const overview = usePolling(() => api.portfolioOverview(), 60_000);
const history = usePolling(() => api.portfolioHistory({start, end}), 60_000);
```

### Task 6.4: Strategy Matrix Page

**File**: `analytics_platform/frontend/src/pages/StrategyMatrixPage.tsx`

**Layout**:
1. **Strategy cards** — One card per strategy showing: name, type (S1/S2/RAEC), trade count, unique symbols, current regime (RAEC only), exposure
2. **Symbol overlap heatmap** — Grid showing which symbols appear across strategies (darker = more overlap). Built with Recharts ScatterChart or CSS grid with color intensity.
3. **Performance comparison table** — Side-by-side: Strategy, Type, Trades, Symbols, Regime, Rebalances, Exposure
4. **Strategy type distribution** — Donut chart: S1 vs S2 vs RAEC exposure split

**Data fetching**: `usePolling(() => api.strategyMatrix(), 60_000)`

### Task 6.5: Update Sidebar, Routes, Types

**Sidebar update** (add to NAV_SECTIONS):
```typescript
{
  label: "Portfolio",
  items: [
    { to: "/portfolio", label: "Overview" },
    { to: "/portfolio/positions", label: "Positions" },
    { to: "/strategies/matrix", label: "Strategy Matrix" },
  ],
},
{
  label: "Execution",
  items: [
    { to: "/execution/slippage", label: "Slippage" },
    { to: "/analytics/trades", label: "Trade Analytics" },
  ],
},
```

**New routes** (add to App.tsx):
```typescript
<Route path="/portfolio" element={<PortfolioPage />} />
<Route path="/portfolio/positions" element={<PortfolioPage />} />
<Route path="/execution/slippage" element={<SlippagePage />} />
<Route path="/analytics/trades" element={<TradeAnalyticsPage />} />
<Route path="/strategies/matrix" element={<StrategyMatrixPage />} />
```

**New TypeScript types**:
```typescript
export interface PortfolioPosition {
  strategy_id: string;
  symbol: string;
  qty: number;
  avg_price: number | null;
  mark_price: number | null;
  notional: number;
  weight_pct: number;
}

export interface PortfolioSummary {
  date_ny: string;
  capital_total: number;
  capital_cash: number;
  capital_invested: number;
  gross_exposure: number;
  net_exposure: number;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  fees_today: number;
}

export interface SlippageSummary {
  mean_bps: number;
  median_bps: number;
  p95_bps: number;
  total_executions: number;
}

export interface StrategyMatrixRow {
  strategy_id: string;
  strategy_type: string;
  trade_count: number;
  unique_symbols: number;
  current_regime: string | null;
  exposure: number | null;
}
```

**New API client methods**:
```typescript
slippage: (args?: { start?: string; end?: string; strategy_id?: string }) =>
  get<KeyValue>(`/api/v1/execution/slippage${toQuery(args ?? {})}`),

tradeAnalytics: (args?: { start?: string; end?: string; strategy_id?: string }) =>
  get<KeyValue>(`/api/v1/analytics/trades${toQuery(args ?? {})}`),

portfolioOverview: () => get<KeyValue>("/api/v1/portfolio/overview"),

portfolioPositions: (args?: { date?: string }) =>
  get<KeyValue>(`/api/v1/portfolio/positions${toQuery(args ?? {})}`),

portfolioHistory: (args?: { start?: string; end?: string }) =>
  get<KeyValue>(`/api/v1/portfolio/history${toQuery(args ?? {})}`),

strategyMatrix: () => get<KeyValue>("/api/v1/strategies/matrix"),
```

### Task 6.6: Upgrade Overview Page

Add a portfolio summary to the top of OverviewPage:
- **Portfolio Health KPIs**: Total Capital, Net Exposure, Strategies Active, Realized P&L Today
- These appear above the existing S1/S2 overview data
- Non-blocking: if portfolio data isn't available yet, skip the section

### Task 6.7: Update Help Page

Add entries for all new Phase 5/6 pages:

| Page | Use It For | When To Act |
|------|-----------|-------------|
| Slippage | Execution quality monitoring — how well trades are filled vs. benchmarks | Act if mean slippage > 10 bps or worsening trend |
| Trade Analytics | Cross-strategy trade frequency and symbol concentration analysis | Review weekly for concentration risk |
| Portfolio Overview | Unified capital, exposure, and P&L across all strategies | Act if exposure exceeds limits or P&L anomalies |
| Strategy Matrix | Cross-strategy comparison and symbol overlap detection | Act if symbol overlap creates unintended concentration |

### Task 6.8: New CSS Styles

```css
/* === Phase 5/6: Portfolio & Analytics Styles === */

/* Portfolio KPIs layout */
.portfolio-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}

/* Slippage badge */
.slippage-good { color: #0f9d58; }
.slippage-warn { color: #dd6b20; }
.slippage-bad { color: #db4437; }

/* Strategy matrix cards */
.matrix-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1rem;
  margin-bottom: 1rem;
}

.matrix-card {
  padding: 1rem;
  border-radius: 8px;
  background: var(--card-bg, #1e1e2e);
  border-left: 4px solid var(--border, #333);
}

.matrix-card.type-s1 { border-left-color: #1f6feb; }
.matrix-card.type-s2 { border-left-color: #8b5cf6; }
.matrix-card.type-raec { border-left-color: #0f9d58; }

/* Overlap heatmap */
.overlap-grid {
  display: grid;
  gap: 2px;
  margin-bottom: 1rem;
}

.overlap-cell {
  width: 100%;
  aspect-ratio: 1;
  border-radius: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
}

/* Position table weight bar */
.weight-bar {
  height: 4px;
  background: #1f6feb;
  border-radius: 2px;
  margin-top: 2px;
}

/* Pie chart container */
.pie-card {
  display: flex;
  justify-content: center;
  padding: 1rem;
}
```

### Task 6.9: API & Frontend Tests

**Backend**: `tests/analytics_platform/test_api_portfolio.py`
- `test_portfolio_overview` — returns capital summary
- `test_portfolio_positions` — returns position list with weight_pct
- `test_portfolio_history` — returns time series
- `test_strategy_matrix` — returns cross-strategy comparison
- `test_portfolio_exports` — CSV export for portfolio_snapshots, portfolio_positions, execution_slippage

**Frontend**: `analytics_platform/frontend/src/__tests__/portfolio_pages.test.tsx`
- Smoke tests for PortfolioPage, SlippagePage, TradeAnalyticsPage, StrategyMatrixPage

### Task 6.10: Final Integration Test

Run full test suite across all 6 phases:
1. Backend: `./venv/bin/pytest tests/analytics_platform -x -v`
2. Strategy: `./venv/bin/pytest tests/ --ignore=tests/analytics_platform -x -v`
3. Frontend typecheck: `cd analytics_platform/frontend && npx tsc --noEmit`
4. Frontend tests: `cd analytics_platform/frontend && npx vitest run`

---

## Extended Data Flow Summary

```
┌──────────────────────────────────────────────────────────────┐
│                    STRATEGY LAYER                            │
├───────────────┬──────────────────┬───────────────────────────┤
│ S1_AVWAP_CORE │ S2_LETF_ORB_AGGRO│ RAEC 401(k) V1-V5+Coord │
│ (Alpaca)      │ (Schwab Manual)   │ (Schwab Manual)          │
└───────┬───────┴────────┬─────────┴──────────┬───────────────┘
        │                │                     │
        ▼                ▼                     ▼
┌──────────────────────────────────────────────────────────────┐
│                    LEDGER LAYER                              │
├──────────────────────────────────────────────────────────────┤
│ PORTFOLIO_DECISIONS/     STRATEGY_SIGNALS/S2_LETF_ORB_AGGRO/ │
│ PORTFOLIO_RISK_CONTROLS/ PORTFOLIO_THROTTLE/  REGIME_E1/     │
│ EXECUTION_SLIPPAGE/      SCHWAB_401K_MANUAL/                 │
│ PORTFOLIO_RISK_ATTRIBUTION/                                  │
│ RAEC_REBALANCE/{STRATEGY_ID}/  (NEW — Phase 1)              │
├──────────────────────────────────────────────────────────────┤
│ analytics/artifacts/portfolio_snapshots/*.json                │
└──────────────────────────────────┬───────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│               build_readmodels() — ETL                       │
├──────────────────────────────────────────────────────────────┤
│ EXISTING TABLES (13):                                        │
│   decision_cycles, decision_intents, entry_rejections,       │
│   strategy_signals, risk_controls_daily, regime_daily,       │
│   gate_blocks, freshness_health, readmodel_meta,             │
│   backtest_runs, backtest_metrics, backtest_entries,          │
│   backtest_monthly                                           │
│                                                              │
│ PHASE 1 TABLES (4):                                          │
│   raec_rebalance_events, raec_allocations,                   │
│   raec_intents, raec_coordinator_runs                        │
│                                                              │
│ PHASE 5 TABLES (4):                                          │
│   execution_slippage, portfolio_snapshots,                   │
│   portfolio_positions, risk_attribution                      │
├──────────────────────────────────────────────────────────────┤
│                    TOTAL: 21 DuckDB tables                   │
└──────────────────────────────────┬───────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                  FastAPI Endpoints                            │
├──────────────────────────────────────────────────────────────┤
│ EXISTING (10):                                               │
│   /overview /decisions /risk/controls /strategies/*           │
│   /signals/s2 /backtests/* /freshness /exports/*             │
│                                                              │
│ PHASE 2 (4):                                                 │
│   /raec/dashboard  /journal  /raec/readiness  /pnl           │
│                                                              │
│ PHASE 5 (2):                                                 │
│   /execution/slippage  /analytics/trades                     │
│                                                              │
│ PHASE 6 (4):                                                 │
│   /portfolio/overview  /portfolio/positions                   │
│   /portfolio/history   /strategies/matrix                    │
├──────────────────────────────────────────────────────────────┤
│                    TOTAL: 20 API endpoints                   │
└──────────────────────────────────┬───────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                   React Frontend                             │
├──────────────────────────────────────────────────────────────┤
│ EXISTING PAGES (7):                                          │
│   Overview, Strategies, S2 Signals, Decisions,               │
│   Risk, Backtests, Help                                      │
│                                                              │
│ PHASE 3 PAGES (4):                                           │
│   RAEC Dashboard, Trade Journal, Readiness, P&L              │
│                                                              │
│ PHASE 5 PAGES (2):                                           │
│   Slippage Dashboard, Trade Analytics                        │
│                                                              │
│ PHASE 6 PAGES (2):                                           │
│   Portfolio Overview, Strategy Matrix                        │
├──────────────────────────────────────────────────────────────┤
│                    TOTAL: 15 pages                           │
└──────────────────────────────────────────────────────────────┘
```

---

## Extended Dependency Order

```
Phase 1-4 (as before)
  └→ Phase 5:
     Task 5.1 (Analytics Fixtures)
       └→ Task 5.2 (Analytics Ingestion)
          └→ Task 5.3 (Readmodel Tests)
          └→ Task 5.4 (Query Functions)
             └→ Task 5.5 (API Endpoints)
                └→ Task 5.6 (Slippage Page)     ← can parallel with 5.7
                └→ Task 5.7 (Trade Analytics Page)
                   └→ Task 5.8 (API Tests)
  └→ Phase 6 (depends on Phase 5.2 for tables):
     Task 6.1 (Portfolio Queries)
       └→ Task 6.2 (Portfolio Endpoints)
          └→ Task 6.3 (Portfolio Page)    ← can parallel with 6.4
          └→ Task 6.4 (Strategy Matrix)
             └→ Task 6.5 (Routes/Types/Sidebar)
                └→ Task 6.6 (Overview Upgrade)
                └→ Task 6.7 (Help Page)
                └→ Task 6.8 (CSS)
                   └→ Task 6.9 (Tests)
                      └→ Task 6.10 (Integration Test)
```

---

## Extended File Inventory

### New Files (Phase 5 & 6)
| File | Phase | Purpose |
|------|-------|---------|
| `tests/analytics_platform/test_readmodels_analytics.py` | 5 | Analytics readmodel tests |
| `tests/analytics_platform/test_api_analytics.py` | 5 | Slippage/trade analytics API tests |
| `tests/analytics_platform/test_api_portfolio.py` | 6 | Portfolio API tests |
| `frontend/src/pages/SlippagePage.tsx` | 5 | Execution slippage dashboard |
| `frontend/src/pages/TradeAnalyticsPage.tsx` | 5 | Trade frequency/concentration |
| `frontend/src/pages/PortfolioPage.tsx` | 6 | Unified portfolio overview |
| `frontend/src/pages/StrategyMatrixPage.tsx` | 6 | Cross-strategy comparison |
| `frontend/src/__tests__/portfolio_pages.test.tsx` | 6 | Frontend smoke tests |

# Institutional Analytics Platform — Implementation Prompts

Sequential Claude Code prompts for building the analytics platform expansion. Execute in order — each prompt depends on prior ones completing successfully.

---

## Phase 1: Data Pipeline

### Prompt 1.1 — Add RAEC Rebalance Ledger Writer to conftest

```
Read the test fixture file at `tests/analytics_platform/conftest.py`. It currently creates sample_repo fixtures with ledger directories for PORTFOLIO_DECISIONS, STRATEGY_SIGNALS, PORTFOLIO_RISK_CONTROLS, PORTFOLIO_THROTTLE, and REGIME_E1.

Add a new ledger directory and fixture data for RAEC rebalance events. In the `sample_repo` fixture:

1. Create directory: `(tmp_path / "ledger" / "RAEC_REBALANCE" / "RAEC_401K_V3").mkdir(parents=True)`
2. Also create: `(tmp_path / "ledger" / "RAEC_REBALANCE" / "RAEC_401K_COORD").mkdir(parents=True)`

3. Write a RAEC rebalance event JSONL record to `ledger/RAEC_REBALANCE/RAEC_401K_V3/2026-02-10.jsonl` with this structure:
```json
{
  "record_type": "RAEC_REBALANCE_EVENT",
  "ts_utc": "2026-02-10T15:00:00+00:00",
  "ny_date": "2026-02-10",
  "book_id": "SCHWAB_401K_MANUAL",
  "strategy_id": "RAEC_401K_V3",
  "regime": "RISK_ON",
  "should_rebalance": true,
  "rebalance_trigger": "daily",
  "targets": {"TQQQ": 35.0, "SOXL": 25.0, "BIL": 40.0},
  "current_allocations": {"SPY": 50.0, "BIL": 50.0},
  "intent_count": 3,
  "intents": [
    {"intent_id": "intent-raec-001", "symbol": "TQQQ", "side": "BUY", "delta_pct": 35.0, "target_pct": 35.0, "current_pct": 0.0},
    {"intent_id": "intent-raec-002", "symbol": "SOXL", "side": "BUY", "delta_pct": 25.0, "target_pct": 25.0, "current_pct": 0.0},
    {"intent_id": "intent-raec-003", "symbol": "SPY", "side": "SELL", "delta_pct": -50.0, "target_pct": 0.0, "current_pct": 50.0}
  ],
  "signals": {"sma200": 180.5, "sma50": 195.3, "vol20": 0.185, "anchor_symbol": "VTI"},
  "momentum_scores": [{"symbol": "TQQQ", "score": 2.45, "ret_6m": 0.152}],
  "portfolio_vol_target": 0.18,
  "portfolio_vol_realized": 0.165,
  "posted": true,
  "notice": null,
  "build_git_sha": "abc123"
}
```

4. Write a coordinator run record to `ledger/RAEC_REBALANCE/RAEC_401K_COORD/2026-02-10.jsonl`:
```json
{
  "record_type": "RAEC_COORDINATOR_RUN",
  "ts_utc": "2026-02-10T15:05:00+00:00",
  "ny_date": "2026-02-10",
  "book_id": "SCHWAB_401K_MANUAL",
  "strategy_id": "RAEC_401K_COORD",
  "capital_split": {"v3": 0.40, "v4": 0.30, "v5": 0.30},
  "sub_strategy_results": {
    "v3": {"regime": "RISK_ON", "should_rebalance": true, "intent_count": 3},
    "v4": {"regime": "TRANSITION", "should_rebalance": false, "intent_count": 0},
    "v5": {"regime": "RISK_ON", "should_rebalance": true, "intent_count": 1}
  }
}
```

Run existing tests to verify nothing breaks: `./venv/bin/pytest tests/analytics_platform -x -v`
```

---

### Prompt 1.2 — Add RAEC Ingestion to build_readmodels.py

```
Read `analytics_platform/backend/readmodels/build_readmodels.py` fully.

Extend the `build_readmodels()` function to ingest RAEC rebalance event JSONL files. Follow the exact same patterns used for PORTFOLIO_DECISIONS and STRATEGY_SIGNALS ingestion.

Add the following after the existing REGIME_E1 section (around line 365) and before the BACKTESTS section:

1. **Add a new SourceHealth entry** to the `sources` list:
   ```python
   SourceHealth(
       source_name="raec_rebalance_events",
       source_glob=str(settings.ledger_dir / "RAEC_REBALANCE" / "**" / "*.jsonl"),
   ),
   ```

2. **Initialize new row lists** at the top with the other row lists (around line 90):
   ```python
   raec_event_rows: list[dict[str, Any]] = []
   raec_allocation_rows: list[dict[str, Any]] = []
   raec_intent_rows: list[dict[str, Any]] = []
   raec_coordinator_rows: list[dict[str, Any]] = []
   ```

3. **Add ingestion section** that:
   - Globs `settings.ledger_dir / "RAEC_REBALANCE"` recursively for `**/*.jsonl`
   - For each record, determine record_type:
     - `"RAEC_REBALANCE_EVENT"`: populate `raec_event_rows` with columns: event_id (use _hash_payload), ny_date, ts_utc, strategy_id, book_id, regime, should_rebalance, rebalance_trigger, intent_count, portfolio_vol_target, portfolio_vol_realized, posted, notice, signals_json, momentum_json, targets_json, current_json, source_file
     - For each symbol in `targets` dict: add to `raec_allocation_rows` with alloc_type="target"
     - For each symbol in `current_allocations` dict: add to `raec_allocation_rows` with alloc_type="current"
     - For each intent in `intents` list: add to `raec_intent_rows` with all intent fields
     - `"RAEC_COORDINATOR_RUN"`: populate `raec_coordinator_rows` with ny_date, ts_utc, capital_split_json, sub_results_json

4. **Add row_counts** entries for the 4 new tables

5. **Write the 4 new DuckDB tables** using `_write_table()` and `_ensure_columns()`:
   - `raec_rebalance_events`
   - `raec_allocations` (columns: ny_date, strategy_id, alloc_type, symbol, weight_pct)
   - `raec_intents` (columns: ny_date, ts_utc, strategy_id, intent_id, symbol, side, delta_pct, target_pct, current_pct)
   - `raec_coordinator_runs` (columns: ny_date, ts_utc, capital_split_json, sub_results_json)

Run tests: `./venv/bin/pytest tests/analytics_platform -x -v`
```

---

### Prompt 1.3 — Add RAEC Readmodel Tests

```
Create a new test file at `tests/analytics_platform/test_readmodels_raec.py`.

Follow the exact pattern from `tests/analytics_platform/test_readmodels.py` — use the `analytics_settings` fixture from conftest.py.

Write these test functions:

1. `test_raec_rebalance_event_ingested(analytics_settings)`:
   - Call `build_readmodels(analytics_settings)`
   - Connect read-only to the DuckDB
   - Assert `raec_rebalance_events` table has >= 1 row
   - Assert the row has strategy_id="RAEC_401K_V3", regime="RISK_ON", should_rebalance=True

2. `test_raec_allocations_target_and_current(analytics_settings)`:
   - Build readmodels, connect, query `raec_allocations`
   - Assert there are rows with alloc_type="target" (TQQQ=35.0, SOXL=25.0, BIL=40.0)
   - Assert there are rows with alloc_type="current" (SPY=50.0, BIL=50.0)

3. `test_raec_intents_parsed(analytics_settings)`:
   - Build readmodels, connect, query `raec_intents`
   - Assert 3 intent rows exist for RAEC_401K_V3
   - Verify one has symbol="TQQQ", side="BUY", delta_pct=35.0

4. `test_raec_coordinator_run_ingested(analytics_settings)`:
   - Build readmodels, connect, query `raec_coordinator_runs`
   - Assert >= 1 row exists
   - Parse capital_split_json and verify v3=0.40

5. `test_raec_freshness_source_exists(analytics_settings)`:
   - Build readmodels, connect, query `freshness_health`
   - Assert a row with source_name="raec_rebalance_events" exists

6. `test_raec_ingestion_idempotent(analytics_settings)`:
   - Call build_readmodels twice
   - Assert both return same data_version and row_counts

All tests must use `pytest.importorskip("duckdb")` at the top of each function. Import `build_readmodels` from `analytics_platform.backend.readmodels.build_readmodels` and `connect_ro` from `analytics_platform.backend.db`.

Run: `./venv/bin/pytest tests/analytics_platform/test_readmodels_raec.py -x -v`
```

---

### Prompt 1.4 — Add Ledger Writer to RAEC Strategies

```
Read these files:
- `strategies/raec_401k_v3.py` (focus on run_strategy function, _save_state, _state_path, RunResult)
- `strategies/raec_401k_v4.py` (same focus)
- `strategies/raec_401k_v5.py` (same focus)
- `strategies/raec_401k_coordinator.py` (same focus)
- `strategies/raec_401k.py` (V1)
- `strategies/raec_401k_v2.py` (V2)

Add a `_write_raec_ledger()` helper function to each strategy file. Place it near the existing `_save_state()` function.

For V1-V5, the function signature and implementation:
```python
def _write_raec_ledger(
    result: RunResult,
    *,
    repo_root: Path,
    targets: dict[str, float],
    current_allocations: dict[str, float],
    signals: dict[str, Any],
    momentum_scores: list[dict[str, Any]],
    build_git_sha: str | None = None,
) -> None:
    """Append a RAEC_REBALANCE_EVENT record to the strategy's ledger."""
    ledger_dir = repo_root / "ledger" / "RAEC_REBALANCE" / STRATEGY_ID
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / f"{result.asof_date}.jsonl"
    record = {
        "record_type": "RAEC_REBALANCE_EVENT",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "ny_date": result.asof_date,
        "book_id": BOOK_ID,
        "strategy_id": STRATEGY_ID,
        "regime": result.regime,
        "should_rebalance": result.should_rebalance,
        "rebalance_trigger": "daily",  # or "monthly" for V1/V2
        "targets": targets,
        "current_allocations": current_allocations,
        "intent_count": len(result.intents),
        "intents": result.intents,
        "signals": signals,
        "momentum_scores": momentum_scores,
        "portfolio_vol_target": TARGET_PORTFOLIO_VOL,
        "portfolio_vol_realized": None,
        "posted": result.posted,
        "notice": result.notice,
        "build_git_sha": build_git_sha,
    }
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
```

Call `_write_raec_ledger()` inside `run_strategy()` right after `_save_state()`, passing the appropriate local variables for targets, current_allocations, and signals. For V1/V2 use rebalance_trigger="monthly".

For the coordinator, write a similar function but with record_type="RAEC_COORDINATOR_RUN" and include capital_split and sub_strategy_results fields instead of targets/signals.

Do NOT modify any existing behavior — only add the ledger append.

Run full test suite: `./venv/bin/pytest tests/ --ignore=tests/analytics_platform -x -v` to ensure no strategy tests break.
```

---

## Phase 2: Backend API

### Prompt 2.1 — Add RAEC Query Functions

```
Read `analytics_platform/backend/api/queries.py` fully.

Add the following new query functions at the bottom of the file, following the existing patterns (_rows helper, _date_clause, parameterized queries):

1. `get_raec_dashboard(conn, start, end, strategy_id=None)`:
   ```python
   def get_raec_dashboard(conn, start: str | None, end: str | None, strategy_id: str | None = None) -> dict[str, Any]:
   ```
   - Query `raec_rebalance_events` for summary stats: total events, rebalances triggered, grouped by strategy_id
   - Include `by_strategy` list with: strategy_id, events count, rebalance count, latest regime, last eval date, portfolio_vol_target
   - Include `regime_history`: ny_date, strategy_id, regime from raec_rebalance_events ordered by date
   - Include `allocation_snapshots`: latest allocations from raec_allocations for each strategy
   - If strategy_id provided, filter all queries to that strategy
   - Use _date_clause for start/end filtering on ny_date

2. `get_journal(conn, start, end, strategy_id=None, symbol=None, side=None, limit=500)`:
   ```python
   def get_journal(conn, *, start: str | None, end: str | None, strategy_id: str | None = None, symbol: str | None = None, side: str | None = None, limit: int = 500) -> dict[str, Any]:
   ```
   - Query `raec_intents` joined with `raec_rebalance_events` on (ny_date, strategy_id) for regime
   - UNION ALL with `decision_intents` (for S1/S2 trades) — for these, regime comes from regime_daily if available
   - Apply optional filters: strategy_id, symbol (upper case), side
   - Order by ny_date DESC, ts_utc DESC
   - Return {count, rows}

3. `get_raec_readiness(conn, settings)`:
   ```python
   def get_raec_readiness(conn, repo_root: Path) -> dict[str, Any]:
   ```
   - For each RAEC strategy (V1-V5, COORD), check:
     - State file exists at `state/strategies/SCHWAB_401K_MANUAL/{STRATEGY_ID}.json`
     - Parse last_eval_date, last_regime, last_known_allocations from state JSON
     - Count ledger files for today in `ledger/RAEC_REBALANCE/{STRATEGY_ID}/`
     - Generate warnings (stale eval, missing state, no allocations)
   - Return strategies list + coordinator summary
   - Import Path at top of file

4. `get_pnl(conn, start, end, strategy_id=None)`:
   ```python
   def get_pnl(conn, start: str | None, end: str | None, strategy_id: str | None = None) -> dict[str, Any]:
   ```
   - Query raec_rebalance_events for rebalance_count and regime_changes per strategy
   - Compute allocation drift series from raec_allocations (difference between target and current totals per day)
   - Return by_strategy list

5. Add new entries to `EXPORT_TABLES`:
   ```python
   "raec_rebalance_events": ("raec_rebalance_events", "ny_date"),
   "raec_allocations": ("raec_allocations", "ny_date"),
   "raec_intents": ("raec_intents", "ny_date"),
   "raec_coordinator_runs": ("raec_coordinator_runs", "ny_date"),
   ```

Run: `./venv/bin/pytest tests/analytics_platform -x -v`
```

---

### Prompt 2.2 — Add RAEC API Endpoints

```
Read `analytics_platform/backend/app.py` fully.

Add new FastAPI endpoints inside `create_app()`, following the exact same pattern as existing endpoints (get runtime, connect_ro, call query function, return _envelope):

1. **RAEC Dashboard**:
   ```python
   @app.get("/api/v1/raec/dashboard")
   def raec_dashboard(
       start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       strategy_id: str | None = None,
   ) -> dict:
       runtime: AnalyticsRuntime = app.state.runtime
       with connect_ro(runtime.settings.db_path) as conn:
           payload = queries.get_raec_dashboard(conn, start, end, strategy_id)
       return _envelope(runtime, payload)
   ```

2. **Trade Journal**:
   ```python
   @app.get("/api/v1/journal")
   def journal(
       start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       strategy_id: str | None = None,
       symbol: str | None = None,
       side: str | None = None,
       limit: int = Query(default=500, ge=1, le=5000),
   ) -> dict:
       runtime: AnalyticsRuntime = app.state.runtime
       with connect_ro(runtime.settings.db_path) as conn:
           payload = queries.get_journal(
               conn, start=start, end=end, strategy_id=strategy_id,
               symbol=symbol, side=side, limit=limit,
           )
       return _envelope(runtime, payload)
   ```

3. **RAEC Readiness**:
   ```python
   @app.get("/api/v1/raec/readiness")
   def raec_readiness() -> dict:
       runtime: AnalyticsRuntime = app.state.runtime
       with connect_ro(runtime.settings.db_path) as conn:
           payload = queries.get_raec_readiness(conn, runtime.settings.repo_root)
       return _envelope(runtime, payload)
   ```

4. **P&L**:
   ```python
   @app.get("/api/v1/pnl")
   def pnl(
       start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       strategy_id: str | None = None,
   ) -> dict:
       runtime: AnalyticsRuntime = app.state.runtime
       with connect_ro(runtime.settings.db_path) as conn:
           payload = queries.get_pnl(conn, start, end, strategy_id)
       return _envelope(runtime, payload)
   ```

Place these after the existing `/api/v1/backtests/runs/{run_id}` endpoint and before the exports endpoint.

Run: `./venv/bin/pytest tests/analytics_platform -x -v`
```

---

### Prompt 2.3 — Add RAEC API Tests

```
Create `tests/analytics_platform/test_api_raec.py`.

Follow the exact pattern from `tests/analytics_platform/test_api.py`: use the `analytics_settings` fixture, importorskip duckdb and fastapi, create app with TestClient.

Write these tests:

```python
from __future__ import annotations
import pytest

def test_raec_dashboard(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from analytics_platform.backend.app import create_app
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)
    app = create_app(settings=analytics_settings)
    client = TestClient(app)

    resp = client.get("/api/v1/raec/dashboard")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "summary" in data
    assert "by_strategy" in data["summary"]

def test_raec_dashboard_filter_strategy(analytics_settings) -> None:
    # Same setup, call with ?strategy_id=RAEC_401K_V3
    # Assert only V3 data returned

def test_journal(analytics_settings) -> None:
    # Call /api/v1/journal, assert 200, assert "rows" in data, assert count >= 3 (from fixture intents)

def test_journal_filter_symbol(analytics_settings) -> None:
    # Call /api/v1/journal?symbol=TQQQ, assert only TQQQ rows

def test_readiness(analytics_settings) -> None:
    # Call /api/v1/raec/readiness, assert 200, assert "strategies" in data

def test_pnl(analytics_settings) -> None:
    # Call /api/v1/pnl, assert 200, assert "by_strategy" in data

def test_raec_exports(analytics_settings) -> None:
    # Call /api/v1/exports/raec_intents.csv, assert 200, assert text/csv content type

def test_strategies_compare_includes_raec(analytics_settings) -> None:
    # Call /api/v1/strategies/compare, verify response still works (backwards compat)
```

Each test should follow the same boilerplate: importorskip, build_readmodels, create_app, TestClient.

Run: `./venv/bin/pytest tests/analytics_platform/test_api_raec.py -x -v`
```

---

## Phase 3: Frontend

### Prompt 3.1 — Add API Client Methods and Types

```
Read `analytics_platform/frontend/src/api.ts` and `analytics_platform/frontend/src/types.ts`.

**In `types.ts`**, add these interfaces at the bottom:

```typescript
export interface RaecRebalanceEvent {
  ny_date: string;
  strategy_id: string;
  regime: string;
  should_rebalance: boolean;
  rebalance_trigger: string;
  intent_count: number;
  portfolio_vol_target: number | null;
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
  regime: string | null;
  posted: boolean | null;
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

export interface AllocationSnapshot {
  ny_date: string;
  strategy_id: string;
  symbol: string;
  weight_pct: number;
  alloc_type: string;
}
```

**In `api.ts`**, add these methods to the `api` object (before the closing `};`):

```typescript
raecDashboard: (args?: { start?: string; end?: string; strategy_id?: string }) =>
  get<KeyValue>(`/api/v1/raec/dashboard${toQuery(args ?? {})}`),

journal: (args?: {
  start?: string;
  end?: string;
  strategy_id?: string;
  symbol?: string;
  side?: string;
  limit?: number;
}) => get<KeyValue>(`/api/v1/journal${toQuery(args ?? {})}`),

raecReadiness: () => get<KeyValue>("/api/v1/raec/readiness"),

pnl: (args?: { start?: string; end?: string; strategy_id?: string }) =>
  get<KeyValue>(`/api/v1/pnl${toQuery(args ?? {})}`),
```

Run frontend type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 3.2 — Create RAEC Dashboard Page

```
Read `analytics_platform/frontend/src/pages/OverviewPage.tsx` as a reference for page structure, data fetching patterns (usePolling, LoadingState, ErrorState, KpiCard), and chart usage (Recharts).

Create `analytics_platform/frontend/src/pages/RaecDashboardPage.tsx`:

```tsx
import { useState } from "react";
import { Bar, BarChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

const STRATEGIES = [
  { id: "", label: "All Strategies" },
  { id: "RAEC_401K_V1", label: "V1 — Core" },
  { id: "RAEC_401K_V2", label: "V2 — Enhanced" },
  { id: "RAEC_401K_V3", label: "V3 — Aggressive" },
  { id: "RAEC_401K_V4", label: "V4 — Global Macro" },
  { id: "RAEC_401K_V5", label: "V5 — AI/Tech" },
  { id: "RAEC_401K_COORD", label: "Coordinator" },
];

export function RaecDashboardPage() {
  const [strategyId, setStrategyId] = useState("");
  const dashboard = usePolling(
    () => api.raecDashboard({ strategy_id: strategyId || undefined }),
    45_000,
  );

  if (dashboard.loading) return <LoadingState text="Loading RAEC dashboard..." />;
  if (dashboard.error) return <ErrorState error={dashboard.error} />;

  const data = dashboard.data?.data as Record<string, any> ?? {};
  const summary = data.summary ?? {};
  const byStrategy = summary.by_strategy ?? [];
  const regimeHistory = data.regime_history ?? [];
  const allocations = data.allocation_snapshots ?? [];

  return (
    <section>
      <h2 className="page-title">RAEC 401(k) Dashboard</h2>

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          This page shows the status of all RAEC 401(k) rotation strategies.
          Monitor <strong>regime transitions</strong> and <strong>rebalance frequency</strong> to ensure
          strategies are responding to market conditions. Check target allocations to verify
          position sizing aligns with risk parameters.
        </p>
      </div>

      <div className="filter-bar">
        <label>
          Strategy:{" "}
          <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
            {STRATEGIES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Total Events" value={summary.total_rebalance_events ?? 0} />
        <KpiCard label="Rebalances Triggered" value={summary.rebalances_triggered ?? 0} />
        <KpiCard label="Active Strategies" value={byStrategy.length} />
      </div>

      {/* Strategy summary table */}
      <div className="table-card">
        <h3>Strategy Status</h3>
        <table>
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Events</th>
              <th>Rebalances</th>
              <th>Regime</th>
              <th>Last Eval</th>
              <th>Vol Target</th>
            </tr>
          </thead>
          <tbody>
            {byStrategy.map((s: any) => (
              <tr key={s.strategy_id}>
                <td>{s.strategy_id}</td>
                <td>{s.events}</td>
                <td>{s.rebalances}</td>
                <td><span className={`regime-badge ${s.current_regime?.toLowerCase().replace("_", "-") ?? ""}`}>{s.current_regime ?? "—"}</span></td>
                <td>{s.last_eval_date ?? "—"}</td>
                <td>{s.portfolio_vol_target != null ? `${(s.portfolio_vol_target * 100).toFixed(0)}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Regime history chart */}
      {regimeHistory.length > 0 && (
        <div className="chart-card">
          <h3>Regime Timeline</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={regimeHistory}>
              <XAxis dataKey="ny_date" />
              <YAxis />
              <Tooltip />
              <Line type="stepAfter" dataKey="regime" stroke="#1f6feb" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Allocation bar chart */}
      {allocations.length > 0 && (
        <div className="chart-card">
          <h3>Current Target Allocations</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={allocations.filter((a: any) => a.alloc_type === "target")}>
              <XAxis dataKey="symbol" />
              <YAxis unit="%" />
              <Tooltip />
              <Bar dataKey="weight_pct" fill="#1f6feb" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
```

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 3.3 — Create Trade Journal Page

```
Read `analytics_platform/frontend/src/pages/S2SignalsPage.tsx` as reference for filter patterns (if any), and `OverviewPage.tsx` for general page structure.

Create `analytics_platform/frontend/src/pages/JournalPage.tsx`:

The page should have:
1. A filter bar with: Strategy dropdown (All + S1_AVWAP_CORE + S2_LETF_ORB_AGGRO + RAEC V1-V5 + Coordinator), Symbol text input, Side dropdown (All/BUY/SELL)
2. KPI row: Total Trades, Buys count, Sells count, Unique Symbols
3. A sortable table with columns: Date, Strategy, Symbol, Side, Delta%, Target%, Current%, Regime, Posted
4. Each row styled with side color (green for BUY, red for SELL)

Use the same patterns as other pages: usePolling with api.journal(), LoadingState, ErrorState. Use useState for filter state. Pass filters to api.journal(). Compute KPI values from the returned rows array.

The strategy dropdown options should be:
```typescript
const ALL_STRATEGIES = [
  { id: "", label: "All Strategies" },
  { id: "S1_AVWAP_CORE", label: "S1 AVWAP Core" },
  { id: "S2_LETF_ORB_AGGRO", label: "S2 LETF ORB" },
  { id: "RAEC_401K_V1", label: "RAEC V1" },
  { id: "RAEC_401K_V2", label: "RAEC V2" },
  { id: "RAEC_401K_V3", label: "RAEC V3" },
  { id: "RAEC_401K_V4", label: "RAEC V4" },
  { id: "RAEC_401K_V5", label: "RAEC V5" },
  { id: "RAEC_401K_COORD", label: "Coordinator" },
];
```

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 3.4 — Create RAEC Readiness Page

```
Read `analytics_platform/frontend/src/pages/OverviewPage.tsx` and `analytics_platform/frontend/src/components/FreshnessBanner.tsx` as reference for status display patterns.

Create `analytics_platform/frontend/src/pages/ReadinessPage.tsx`:

The page should have:
1. Overall status banner (green if no warnings across all strategies, yellow/red if warnings exist)
2. A grid of strategy cards (one per RAEC strategy: V1-V5 + Coordinator)
3. Each card shows:
   - Strategy name
   - State file status: green checkmark or red X
   - Last eval date (with "stale" warning if > 3 days ago)
   - Current regime with colored badge (RISK_ON=green, TRANSITION=yellow, RISK_OFF=red)
   - Allocation count and total weight
   - Ledger files today count
   - Warning list (if any)

Use `api.raecReadiness()` with usePolling at 60_000ms interval.

CSS classes to use:
- `.readiness-card` for each strategy card
- `.readiness-ok` / `.readiness-warn` / `.readiness-error` for card border color
- `.regime-badge.risk-on` / `.regime-badge.transition` / `.regime-badge.risk-off` for regime colors

Example card structure:
```tsx
<div className={`readiness-card ${warnings.length === 0 ? "readiness-ok" : "readiness-warn"}`}>
  <h4>{strategy.strategy_id}</h4>
  <div>State: {strategy.state_file_exists ? "OK" : "MISSING"}</div>
  <div>Last Eval: {strategy.last_eval_date ?? "Never"}</div>
  <div>Regime: <span className={`regime-badge ${strategy.last_regime?.toLowerCase().replace("_", "-")}`}>{strategy.last_regime ?? "—"}</span></div>
  <div>Allocations: {strategy.allocation_count} ({strategy.total_weight_pct.toFixed(1)}%)</div>
  <div>Ledger Today: {strategy.ledger_files_today}</div>
  {strategy.warnings.length > 0 && (
    <ul className="warning-list">
      {strategy.warnings.map((w, i) => <li key={i}>{w}</li>)}
    </ul>
  )}
</div>
```

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 3.5 — Create P&L Page

```
Read `analytics_platform/frontend/src/pages/OverviewPage.tsx` as reference for chart patterns.

Create `analytics_platform/frontend/src/pages/PnlPage.tsx`:

The page should have:
1. Strategy selector dropdown (same as RAEC Dashboard)
2. KPI row: Rebalance Count, Regime Changes, strategies with data
3. Drift chart: A Recharts LineChart showing allocation drift over time per strategy
4. Rebalance frequency summary: A table or bar chart showing rebalance counts per strategy

Use `api.pnl({ strategy_id })` with usePolling at 45_000ms.

```tsx
import { useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

// Strategy dropdown options same as RaecDashboardPage

export function PnlPage() {
  const [strategyId, setStrategyId] = useState("");
  const pnl = usePolling(() => api.pnl({ strategy_id: strategyId || undefined }), 45_000);

  if (pnl.loading) return <LoadingState text="Loading P&L data..." />;
  if (pnl.error) return <ErrorState error={pnl.error} />;

  const data = pnl.data?.data as Record<string, any> ?? {};
  const byStrategy = data.by_strategy ?? [];

  const totalRebalances = byStrategy.reduce((sum: number, s: any) => sum + (s.rebalance_count ?? 0), 0);
  const totalRegimeChanges = byStrategy.reduce((sum: number, s: any) => sum + (s.regime_changes ?? 0), 0);

  return (
    <section>
      <h2 className="page-title">P&L & Drift Analysis</h2>
      {/* helper card, filter bar, KPIs, charts following standard patterns */}
    </section>
  );
}
```

Implement the full page with helper card explanation, filter bar, KPI grid, and charts.

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

## Phase 4: Integration

### Prompt 4.1 — Update Routes and Sidebar

```
Read these files:
- `analytics_platform/frontend/src/App.tsx`
- `analytics_platform/frontend/src/components/Layout.tsx`

**In `App.tsx`**, add imports for the 4 new pages and add routes:

```tsx
import { JournalPage } from "./pages/JournalPage";
import { PnlPage } from "./pages/PnlPage";
import { RaecDashboardPage } from "./pages/RaecDashboardPage";
import { ReadinessPage } from "./pages/ReadinessPage";

// Inside <Routes>, add before the catch-all:
<Route path="/raec" element={<RaecDashboardPage />} />
<Route path="/raec/readiness" element={<ReadinessPage />} />
<Route path="/journal" element={<JournalPage />} />
<Route path="/pnl" element={<PnlPage />} />
```

**In `Layout.tsx`**, replace the flat `NAV_ITEMS` array with a grouped sidebar. Change the component to render sections with headers:

```tsx
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

Update the nav rendering to show section labels as `<div className="nav-section-label">`:

```tsx
<nav className="nav-list">
  {NAV_SECTIONS.map((section) => (
    <div key={section.label}>
      <div className="nav-section-label">{section.label}</div>
      {section.items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
          end={item.to === "/"}
        >
          {item.label}
        </NavLink>
      ))}
    </div>
  ))}
</nav>
```

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 4.2 — Add Styles for New Components

```
Read `analytics_platform/frontend/src/styles.css`.

Append these CSS rules at the end of the file. Do NOT modify any existing styles.

```css
/* === Phase 4: RAEC & Analytics Styles === */

/* Strategy filter bar */
.filter-bar {
  display: flex;
  gap: 1rem;
  align-items: center;
  padding: 0.75rem 1rem;
  background: var(--card-bg, #1e1e2e);
  border-radius: 8px;
  margin-bottom: 1rem;
}

.filter-bar label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: var(--text-secondary, #a0a0b0);
}

.filter-bar select,
.filter-bar input {
  padding: 0.35rem 0.6rem;
  border-radius: 4px;
  border: 1px solid var(--border, #333);
  background: var(--input-bg, #2a2a3e);
  color: var(--text-primary, #e0e0e0);
  font-size: 0.85rem;
}

/* Regime badges */
.regime-badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.regime-badge.risk-on {
  background: #0f9d5820;
  color: #0f9d58;
  border: 1px solid #0f9d5840;
}

.regime-badge.transition {
  background: #dd6b2020;
  color: #dd6b20;
  border: 1px solid #dd6b2040;
}

.regime-badge.risk-off {
  background: #db443720;
  color: #db4437;
  border: 1px solid #db443740;
}

/* Readiness cards */
.readiness-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
  margin-bottom: 1rem;
}

.readiness-card {
  padding: 1rem;
  border-radius: 8px;
  background: var(--card-bg, #1e1e2e);
  border-left: 4px solid var(--border, #333);
}

.readiness-card h4 {
  margin: 0 0 0.75rem 0;
  font-size: 0.95rem;
}

.readiness-card div {
  font-size: 0.85rem;
  margin-bottom: 0.35rem;
  color: var(--text-secondary, #a0a0b0);
}

.readiness-ok {
  border-left-color: #0f9d58;
}

.readiness-warn {
  border-left-color: #dd6b20;
}

.readiness-error {
  border-left-color: #db4437;
}

.warning-list {
  margin: 0.5rem 0 0 0;
  padding-left: 1.2rem;
  font-size: 0.8rem;
  color: #dd6b20;
}

/* Journal table */
.journal-table {
  width: 100%;
  font-size: 0.85rem;
}

.journal-table .side-buy {
  color: #0f9d58;
  font-weight: 600;
}

.journal-table .side-sell {
  color: #db4437;
  font-weight: 600;
}

/* Nav section labels */
.nav-section-label {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-secondary, #666);
  padding: 1rem 1rem 0.25rem 1rem;
  font-weight: 600;
}

.nav-section-label:first-child {
  padding-top: 0.5rem;
}
```

Run: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 4.3 — Update Overview Page with RAEC Summary

```
Read `analytics_platform/frontend/src/pages/OverviewPage.tsx`.

Add a RAEC summary section below the existing chart. This requires:

1. Add a new usePolling call for the RAEC dashboard data:
   ```tsx
   const raec = usePolling(() => api.raecDashboard(), 45_000);
   ```

2. Add raec to the loading check (but don't block on it — use optional rendering)

3. After the chart-card div, add a RAEC summary section:
   ```tsx
   {raec.data && !raec.error && (
     <div className="table-card">
       <h3>RAEC 401(k) Status</h3>
       <table>
         <thead>
           <tr>
             <th>Strategy</th>
             <th>Regime</th>
             <th>Last Eval</th>
             <th>Rebalances</th>
           </tr>
         </thead>
         <tbody>
           {((raec.data.data as any)?.summary?.by_strategy ?? []).map((s: any) => (
             <tr key={s.strategy_id}>
               <td>{s.strategy_id}</td>
               <td>
                 <span className={`regime-badge ${s.current_regime?.toLowerCase().replace("_", "-") ?? ""}`}>
                   {s.current_regime ?? "—"}
                 </span>
               </td>
               <td>{s.last_eval_date ?? "—"}</td>
               <td>{s.rebalances ?? 0}</td>
             </tr>
           ))}
         </tbody>
       </table>
     </div>
   )}
   ```

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 4.4 — Update Help Page

```
Read `analytics_platform/frontend/src/pages/HelpPage.tsx`.

Add new rows to the "Page-by-Page Purpose" table in the `<tbody>`:

```tsx
<tr>
  <td>RAEC Dashboard</td>
  <td>Regime status, allocation targets, rebalance history for all RAEC 401(k) strategies.</td>
  <td>Act if regime changes unexpectedly or rebalances stop firing.</td>
</tr>
<tr>
  <td>Readiness</td>
  <td>Pre-market check that all RAEC strategies have valid state and recent evaluations.</td>
  <td>Act if any strategy shows warnings, stale eval dates, or missing state files.</td>
</tr>
<tr>
  <td>Trade Journal</td>
  <td>Unified trade log across all strategies (S1, S2, RAEC V1-V5).</td>
  <td>Review weekly for trade pattern analysis and strategy concentration.</td>
</tr>
<tr>
  <td>P&amp;L</td>
  <td>Allocation drift tracking and rebalance frequency analysis.</td>
  <td>Act if drift exceeds thresholds consistently or rebalance frequency drops.</td>
</tr>
```

Also update the "Recommended Daily Workflow" section to include:
"5) Check <strong>RAEC Dashboard</strong> for regime status and rebalance activity across 401(k) strategies.
6) Use <strong>Readiness</strong> before market open to verify all strategies have valid state."

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 4.5 — Frontend Smoke Tests

```
Read `analytics_platform/frontend/src/__tests__/layout.test.tsx` for test patterns.

Create `analytics_platform/frontend/src/__tests__/raec_pages.test.tsx`:

Write smoke tests that verify each new page component renders without crashing. Use `@testing-library/react` with `MemoryRouter` wrapping:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the api module
vi.mock("../api", () => ({
  api: {
    raecDashboard: vi.fn().mockResolvedValue({
      data: { summary: { total_rebalance_events: 0, by_strategy: [] }, regime_history: [], allocation_snapshots: [] },
    }),
    journal: vi.fn().mockResolvedValue({ data: { count: 0, rows: [] } }),
    raecReadiness: vi.fn().mockResolvedValue({ data: { strategies: [], coordinator: {} } }),
    pnl: vi.fn().mockResolvedValue({ data: { by_strategy: [] } }),
  },
}));

import { RaecDashboardPage } from "../pages/RaecDashboardPage";
import { JournalPage } from "../pages/JournalPage";
import { ReadinessPage } from "../pages/ReadinessPage";
import { PnlPage } from "../pages/PnlPage";

describe("RAEC pages render without crashing", () => {
  it("RaecDashboardPage", async () => {
    render(<MemoryRouter><RaecDashboardPage /></MemoryRouter>);
    // Should show loading initially
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("JournalPage", async () => {
    render(<MemoryRouter><JournalPage /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("ReadinessPage", async () => {
    render(<MemoryRouter><ReadinessPage /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("PnlPage", async () => {
    render(<MemoryRouter><PnlPage /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});
```

Run: `cd analytics_platform/frontend && npx vitest run`
```

---

### Prompt 4.6 — Final Integration Test

```
Run the full test suite to verify everything works together:

1. Backend tests: `./venv/bin/pytest tests/analytics_platform -x -v`
2. Strategy tests (no regressions): `./venv/bin/pytest tests/ --ignore=tests/analytics_platform -x -v`
3. Frontend type check: `cd analytics_platform/frontend && npx tsc --noEmit`
4. Frontend tests: `cd analytics_platform/frontend && npx vitest run`

Fix any failures. If tests pass, report the final test counts.
```

---

---

## Phase 5: S1/S2 Trade Analytics & Execution Quality

### Prompt 5.1 — Add Analytics Fixture Data to conftest

```
Read `tests/analytics_platform/conftest.py`.

Add fixture data for the analytics module's data sources. In the `sample_repo` fixture, after the existing RAEC ledger data:

1. Create `(tmp_path / "ledger" / "EXECUTION_SLIPPAGE").mkdir(parents=True)`
2. Write 3 SlippageEvent records to `ledger/EXECUTION_SLIPPAGE/2026-02-10.jsonl`:

Record 1 (mega cap, S1):
```json
{"schema_version":1,"record_type":"EXECUTION_SLIPPAGE","date_ny":"2026-02-10","symbol":"AAPL","strategy_id":"S1_AVWAP_CORE","expected_price":185.50,"ideal_fill_price":185.45,"actual_fill_price":185.52,"slippage_bps":3.78,"adv_shares_20d":55000000.0,"liquidity_bucket":"mega","fill_ts_utc":"2026-02-10T15:30:00+00:00","time_of_day_bucket":"10:30-11:00"}
```

Record 2 (mid cap, S1):
```json
{"schema_version":1,"record_type":"EXECUTION_SLIPPAGE","date_ny":"2026-02-10","symbol":"CRWD","strategy_id":"S1_AVWAP_CORE","expected_price":320.00,"ideal_fill_price":319.80,"actual_fill_price":320.45,"slippage_bps":20.32,"adv_shares_20d":900000.0,"liquidity_bucket":"mid","fill_ts_utc":"2026-02-10T14:45:00+00:00","time_of_day_bucket":"09:45-10:00"}
```

Record 3 (large cap, S2):
```json
{"schema_version":1,"record_type":"EXECUTION_SLIPPAGE","date_ny":"2026-02-10","symbol":"TQQQ","strategy_id":"S2_LETF_ORB_AGGRO","expected_price":75.00,"ideal_fill_price":74.95,"actual_fill_price":75.08,"slippage_bps":17.35,"adv_shares_20d":3500000.0,"liquidity_bucket":"large","fill_ts_utc":"2026-02-10T14:35:00+00:00","time_of_day_bucket":"09:35-10:00"}
```

3. Create `(tmp_path / "ledger" / "PORTFOLIO_RISK_ATTRIBUTION").mkdir(parents=True)`
4. Write 1 risk attribution record to `ledger/PORTFOLIO_RISK_ATTRIBUTION/2026-02-10.jsonl`:
```json
{"record_type":"PORTFOLIO_RISK_ATTRIBUTION","schema_version":1,"date_ny":"2026-02-10","ts_utc":"2026-02-10T21:00:00+00:00","decision_id":"risk-attr-001","strategy_id":"S1_AVWAP_CORE","symbol":"AAPL","action":"SIZE_REDUCE","reason_codes":["regime_transition","vol_spike"],"pct_delta":-15.0,"baseline_exposure":50000.0}
```

5. Create `(tmp_path / "analytics" / "artifacts" / "portfolio_snapshots").mkdir(parents=True, exist_ok=True)`
6. Write a PortfolioSnapshot JSON to `analytics/artifacts/portfolio_snapshots/2026-02-10.json`:
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

Run existing tests to verify nothing breaks: `./venv/bin/pytest tests/analytics_platform -x -v`
```

---

### Prompt 5.2 — Add Analytics Ingestion to build_readmodels.py

```
Read `analytics_platform/backend/readmodels/build_readmodels.py` fully.

Extend `build_readmodels()` to ingest 3 new data sources. Follow the exact same patterns used for existing ingestion (glob files, iterate records, build row lists, _write_table, _ensure_columns).

1. **Add new SourceHealth entries** to the `sources` list:
   ```python
   SourceHealth(
       source_name="execution_slippage",
       source_glob=str(settings.ledger_dir / "EXECUTION_SLIPPAGE" / "*.jsonl"),
   ),
   SourceHealth(
       source_name="portfolio_snapshots",
       source_glob=str(settings.repo_root / "analytics" / "artifacts" / "portfolio_snapshots" / "*.json"),
   ),
   ```

2. **Initialize new row lists** alongside existing ones:
   ```python
   slippage_rows: list[dict[str, Any]] = []
   snapshot_rows: list[dict[str, Any]] = []
   position_rows: list[dict[str, Any]] = []
   risk_attr_rows: list[dict[str, Any]] = []
   ```

3. **EXECUTION_SLIPPAGE ingestion**:
   - Glob `settings.ledger_dir / "EXECUTION_SLIPPAGE" / "*.jsonl"`
   - For each JSONL record with record_type="EXECUTION_SLIPPAGE", add to slippage_rows:
     date_ny, symbol, strategy_id, expected_price, ideal_fill_price, actual_fill_price,
     slippage_bps, adv_shares_20d, liquidity_bucket, fill_ts_utc, time_of_day_bucket, source_file

4. **PORTFOLIO_SNAPSHOTS ingestion**:
   - Glob `settings.repo_root / "analytics" / "artifacts" / "portfolio_snapshots" / "*.json"`
   - For each JSON file, parse with json.load (not JSONL — these are single JSON files)
   - Add to snapshot_rows: date_ny, run_id, strategy_ids_json (json.dumps of strategy_ids list),
     capital_total (from capital.total), capital_cash (from capital.cash),
     capital_invested (from capital.invested), gross_exposure, net_exposure,
     realized_pnl (from pnl.realized_today), unrealized_pnl (from pnl.unrealized),
     fees_today (from pnl.fees_today), source_file
   - For each position in positions list, add to position_rows:
     date_ny, strategy_id, symbol, qty, avg_price, mark_price, notional

5. **PORTFOLIO_RISK_ATTRIBUTION ingestion**:
   - Glob `settings.ledger_dir / "PORTFOLIO_RISK_ATTRIBUTION" / "*.jsonl"`
   - For each record, add to risk_attr_rows: date_ny, record_json (json.dumps of full record), source_file

6. **Write the 4 new tables** using _write_table and _ensure_columns:
   - `execution_slippage` from slippage_rows
   - `portfolio_snapshots` from snapshot_rows
   - `portfolio_positions` from position_rows
   - `risk_attribution` from risk_attr_rows

7. **Add row_counts** for the 4 new tables.

Important: For portfolio snapshot files, use `json.load()` on each file (they're regular JSON, not JSONL). Handle missing keys gracefully with `.get()` and default to None/0.

Run: `./venv/bin/pytest tests/analytics_platform -x -v`
```

---

### Prompt 5.3 — Add Analytics Readmodel Tests

```
Create `tests/analytics_platform/test_readmodels_analytics.py`.

Follow the exact pattern from `tests/analytics_platform/test_readmodels.py` and the RAEC tests — use `analytics_settings` fixture, `pytest.importorskip("duckdb")`.

Write these tests:

1. `test_slippage_events_ingested(analytics_settings)`:
   - Build readmodels, connect RO, query `execution_slippage`
   - Assert >= 3 rows exist
   - Check one row has symbol="AAPL", strategy_id="S1_AVWAP_CORE", slippage_bps close to 3.78

2. `test_slippage_liquidity_buckets(analytics_settings)`:
   - Build readmodels, query `SELECT DISTINCT liquidity_bucket FROM execution_slippage`
   - Assert buckets include "mega", "mid", "large"

3. `test_portfolio_snapshot_ingested(analytics_settings)`:
   - Build readmodels, query `portfolio_snapshots`
   - Assert >= 1 row, check capital_total=100000.0, gross_exposure=55000.0

4. `test_portfolio_positions_ingested(analytics_settings)`:
   - Build readmodels, query `portfolio_positions`
   - Assert 3 rows (AAPL, MSFT, TQQQ)
   - Check AAPL row has qty=100, mark_price=185.50, notional=18550.0

5. `test_risk_attribution_ingested(analytics_settings)`:
   - Build readmodels, query `risk_attribution`
   - Assert >= 1 row, parse record_json, check action="SIZE_REDUCE"

6. `test_analytics_freshness_sources(analytics_settings)`:
   - Build readmodels, query freshness_health
   - Assert rows with source_name "execution_slippage" and "portfolio_snapshots" exist

Run: `./venv/bin/pytest tests/analytics_platform/test_readmodels_analytics.py -x -v`
```

---

### Prompt 5.4 — Add Execution Quality & Trade Analytics Query Functions

```
Read `analytics_platform/backend/api/queries.py` fully.

Add these query functions at the bottom, following existing patterns (_rows, _date_clause, parameterized queries):

1. `get_slippage_dashboard(conn, start: str | None, end: str | None, strategy_id: str | None = None) -> dict[str, Any]`:

   Implementation:
   - Build WHERE clause with _date_clause on date_ny + optional strategy_id filter
   - **summary**: Query `SELECT COUNT(*) as total, AVG(slippage_bps) as mean_bps FROM execution_slippage {where}`
     Also compute median (use PERCENTILE_CONT(0.5) in DuckDB) and p95 (PERCENTILE_CONT(0.95))
   - **by_bucket**: `SELECT liquidity_bucket, COUNT(*) as count, AVG(slippage_bps) as mean_bps, MIN(slippage_bps) as min_bps, MAX(slippage_bps) as max_bps FROM execution_slippage {where} GROUP BY liquidity_bucket ORDER BY liquidity_bucket`
   - **by_time**: Same but GROUP BY time_of_day_bucket ORDER BY time_of_day_bucket
   - **by_symbol**: `SELECT symbol, COUNT(*) as count, AVG(slippage_bps) as mean_bps FROM execution_slippage {where} GROUP BY symbol ORDER BY ABS(AVG(slippage_bps)) DESC LIMIT 10`
   - **trend**: `SELECT date_ny, AVG(slippage_bps) as mean_bps, COUNT(*) as count FROM execution_slippage {where} GROUP BY date_ny ORDER BY date_ny`
   - Return dict with keys: summary, by_bucket, by_time, by_symbol, trend

2. `get_trade_analytics(conn, start: str | None, end: str | None, strategy_id: str | None = None) -> dict[str, Any]`:

   Implementation:
   - **per_strategy**: Query decision_intents (for S1/S2) UNION ALL raec_intents (for RAEC):
     ```sql
     SELECT strategy_id, COUNT(*) as trade_count,
            COUNT(DISTINCT symbol) as unique_symbols,
            SUM(CASE WHEN side='BUY' THEN 1 ELSE 0 END) as buys,
            SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) as sells
     FROM (
       SELECT strategy_id, symbol, side, ny_date FROM decision_intents
       UNION ALL
       SELECT strategy_id, symbol, side, ny_date FROM raec_intents
     ) combined
     {where on ny_date}
     GROUP BY strategy_id
     ORDER BY trade_count DESC
     ```
   - **daily_frequency**: `SELECT ny_date, COUNT(*) as count FROM combined {where} GROUP BY ny_date ORDER BY ny_date`
   - **symbol_concentration**: `SELECT symbol, COUNT(*) as count FROM combined {where} GROUP BY symbol ORDER BY count DESC LIMIT 15`
   - Return dict with keys: per_strategy, daily_frequency, symbol_concentration

3. Add to EXPORT_TABLES:
   ```python
   "execution_slippage": ("execution_slippage", "date_ny"),
   "portfolio_snapshots": ("portfolio_snapshots", "date_ny"),
   "portfolio_positions": ("portfolio_positions", "date_ny"),
   ```

Run: `./venv/bin/pytest tests/analytics_platform -x -v`
```

---

### Prompt 5.5 — Add Execution Quality API Endpoints

```
Read `analytics_platform/backend/app.py` fully.

Add 2 new endpoints, following the existing pattern (get runtime, connect_ro, call query function, return _envelope):

1. **Slippage Dashboard**:
   ```python
   @app.get("/api/v1/execution/slippage")
   def execution_slippage(
       start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       strategy_id: str | None = None,
   ) -> dict:
       runtime: AnalyticsRuntime = app.state.runtime
       with connect_ro(runtime.settings.db_path) as conn:
           payload = queries.get_slippage_dashboard(conn, start, end, strategy_id)
       return _envelope(runtime, payload)
   ```

2. **Trade Analytics**:
   ```python
   @app.get("/api/v1/analytics/trades")
   def analytics_trades(
       start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       strategy_id: str | None = None,
   ) -> dict:
       runtime: AnalyticsRuntime = app.state.runtime
       with connect_ro(runtime.settings.db_path) as conn:
           payload = queries.get_trade_analytics(conn, start, end, strategy_id)
       return _envelope(runtime, payload)
   ```

Place these after the RAEC endpoints and before the exports endpoint.

Run: `./venv/bin/pytest tests/analytics_platform -x -v`
```

---

### Prompt 5.6 — Create Slippage Dashboard Page

```
Read `analytics_platform/frontend/src/pages/OverviewPage.tsx` for reference patterns.

Create `analytics_platform/frontend/src/pages/SlippagePage.tsx`:

```tsx
import { useState } from "react";
import { Bar, BarChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell } from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

const STRATEGIES = [
  { id: "", label: "All Strategies" },
  { id: "S1_AVWAP_CORE", label: "S1 AVWAP Core" },
  { id: "S2_LETF_ORB_AGGRO", label: "S2 LETF ORB" },
];

const BUCKET_COLORS: Record<string, string> = {
  mega: "#0f9d58",
  large: "#1f6feb",
  mid: "#dd6b20",
  small: "#db4437",
};

export function SlippagePage() {
  const [strategyId, setStrategyId] = useState("");
  const slippage = usePolling(
    () => api.slippage({ strategy_id: strategyId || undefined }),
    60_000,
  );

  if (slippage.loading) return <LoadingState text="Loading slippage data..." />;
  if (slippage.error) return <ErrorState error={slippage.error} />;

  const data = slippage.data?.data as Record<string, any> ?? {};
  const summary = data.summary ?? {};
  const byBucket = data.by_bucket ?? [];
  const byTime = data.by_time ?? [];
  const bySymbol = data.by_symbol ?? [];
  const trend = data.trend ?? [];

  const slippageClass = (bps: number) =>
    bps <= 5 ? "slippage-good" : bps <= 15 ? "slippage-warn" : "slippage-bad";

  return (
    <section>
      <h2 className="page-title">Execution Slippage</h2>

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          Slippage measures the difference between the <strong>ideal fill price</strong> (benchmark)
          and the <strong>actual fill price</strong> in basis points. Lower is better.
          Monitor by <strong>liquidity bucket</strong> to understand market impact and by
          <strong> time of day</strong> to optimize execution timing.
        </p>
      </div>

      <div className="filter-bar">
        <label>
          Strategy:{" "}
          <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
            {STRATEGIES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Mean Slippage" value={`${(summary.mean_bps ?? 0).toFixed(1)} bps`} />
        <KpiCard label="Median Slippage" value={`${(summary.median_bps ?? 0).toFixed(1)} bps`} />
        <KpiCard label="P95 Slippage" value={`${(summary.p95_bps ?? 0).toFixed(1)} bps`} />
        <KpiCard label="Total Executions" value={summary.total ?? 0} />
      </div>

      {/* By Liquidity Bucket */}
      {byBucket.length > 0 && (
        <div className="chart-card">
          <h3>Slippage by Liquidity Bucket</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byBucket}>
              <XAxis dataKey="liquidity_bucket" />
              <YAxis unit=" bps" />
              <Tooltip />
              <Bar dataKey="mean_bps">
                {byBucket.map((entry: any, idx: number) => (
                  <Cell key={idx} fill={BUCKET_COLORS[entry.liquidity_bucket] ?? "#1f6feb"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* By Time of Day */}
      {byTime.length > 0 && (
        <div className="chart-card">
          <h3>Slippage by Time of Day</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byTime}>
              <XAxis dataKey="time_of_day_bucket" angle={-45} textAnchor="end" height={80} />
              <YAxis unit=" bps" />
              <Tooltip />
              <Bar dataKey="mean_bps" fill="#8b5cf6" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Top Symbols by Slippage */}
      {bySymbol.length > 0 && (
        <div className="table-card">
          <h3>Top Symbols by Absolute Slippage</h3>
          <table>
            <thead>
              <tr><th>Symbol</th><th>Executions</th><th>Mean Slippage (bps)</th></tr>
            </thead>
            <tbody>
              {bySymbol.map((row: any) => (
                <tr key={row.symbol}>
                  <td>{row.symbol}</td>
                  <td>{row.count}</td>
                  <td className={slippageClass(Math.abs(row.mean_bps))}>{row.mean_bps.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Trend */}
      {trend.length > 0 && (
        <div className="chart-card">
          <h3>Daily Average Slippage Trend</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={trend}>
              <XAxis dataKey="date_ny" />
              <YAxis unit=" bps" />
              <Tooltip />
              <Line type="monotone" dataKey="mean_bps" stroke="#1f6feb" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
```

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 5.7 — Create Trade Analytics Page

```
Read `analytics_platform/frontend/src/pages/OverviewPage.tsx` and `analytics_platform/frontend/src/pages/JournalPage.tsx` for reference patterns.

Create `analytics_platform/frontend/src/pages/TradeAnalyticsPage.tsx`:

The page should have:

1. **Strategy selector** — dropdown with All + all strategy IDs
2. **KPI row** — Total Trades, Unique Symbols, Active Strategies, Buy/Sell Ratio
3. **Trade frequency chart** — Recharts LineChart of daily trade count over time (from daily_frequency data)
4. **Per-strategy breakdown table** — Columns: Strategy, Trade Count, Unique Symbols, Buys, Sells, Buy %
5. **Symbol concentration chart** — Recharts horizontal BarChart of top 15 symbols by trade count

Use `api.tradeAnalytics({strategy_id})` with usePolling at 45_000ms.

Strategy options:
```typescript
const ALL_STRATEGIES = [
  { id: "", label: "All Strategies" },
  { id: "S1_AVWAP_CORE", label: "S1 AVWAP Core" },
  { id: "S2_LETF_ORB_AGGRO", label: "S2 LETF ORB" },
  { id: "RAEC_401K_V1", label: "RAEC V1" },
  { id: "RAEC_401K_V2", label: "RAEC V2" },
  { id: "RAEC_401K_V3", label: "RAEC V3" },
  { id: "RAEC_401K_V4", label: "RAEC V4" },
  { id: "RAEC_401K_V5", label: "RAEC V5" },
  { id: "RAEC_401K_COORD", label: "Coordinator" },
];
```

Include a helper card explaining: "This page shows trade activity across all strategies. Use it to understand which strategies are most active, which symbols are traded most frequently, and whether trading activity is increasing or decreasing over time."

Compute KPIs from per_strategy array:
- Total Trades: sum of all trade_count
- Unique Symbols: (fetch from response or dedupe)
- Active Strategies: count of per_strategy rows
- Buy/Sell Ratio: total buys / total sells

For the symbol concentration chart, use layout="vertical" on BarChart for horizontal bars.

Follow the same component structure as other pages: usePolling, LoadingState, ErrorState, KpiCard grid, chart-cards.

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 5.8 — Add Analytics API Tests

```
Create `tests/analytics_platform/test_api_analytics.py`.

Follow the exact pattern from `tests/analytics_platform/test_api_raec.py`: use analytics_settings fixture, importorskip duckdb and fastapi, build_readmodels, create_app, TestClient.

Write these tests:

1. `test_slippage_dashboard(analytics_settings)`:
   - GET /api/v1/execution/slippage
   - Assert 200, assert "summary" in data
   - Assert summary has "mean_bps" and "total"
   - Assert "by_bucket" in data, assert len >= 1

2. `test_slippage_filter_strategy(analytics_settings)`:
   - GET /api/v1/execution/slippage?strategy_id=S1_AVWAP_CORE
   - Assert 200, check that only S1 data returned (by checking by_symbol doesn't include TQQQ)

3. `test_trade_analytics(analytics_settings)`:
   - GET /api/v1/analytics/trades
   - Assert 200, assert "per_strategy" in data
   - Assert at least one strategy row exists

4. `test_trade_analytics_daily_frequency(analytics_settings)`:
   - GET /api/v1/analytics/trades
   - Assert "daily_frequency" in data
   - Assert len >= 1

5. `test_slippage_export(analytics_settings)`:
   - GET /api/v1/exports/execution_slippage.csv
   - Assert 200, assert content-type contains "text/csv"

6. `test_portfolio_snapshots_export(analytics_settings)`:
   - GET /api/v1/exports/portfolio_snapshots.csv
   - Assert 200

Run: `./venv/bin/pytest tests/analytics_platform/test_api_analytics.py -x -v`
```

---

### Prompt 5.9 — Add Phase 5 Types and API Client Methods

```
Read `analytics_platform/frontend/src/types.ts` and `analytics_platform/frontend/src/api.ts`.

**In types.ts**, add:

```typescript
export interface SlippageSummary {
  mean_bps: number;
  median_bps: number;
  p95_bps: number;
  total: number;
}

export interface SlippageBucket {
  liquidity_bucket: string;
  count: number;
  mean_bps: number;
  min_bps: number;
  max_bps: number;
}

export interface SlippageTimeBucket {
  time_of_day_bucket: string;
  count: number;
  mean_bps: number;
}

export interface TradeAnalyticsStrategy {
  strategy_id: string;
  trade_count: number;
  unique_symbols: number;
  buys: number;
  sells: number;
}

export interface SymbolConcentration {
  symbol: string;
  count: number;
}
```

**In api.ts**, add to the api object:

```typescript
slippage: (args?: { start?: string; end?: string; strategy_id?: string }) =>
  get<KeyValue>(`/api/v1/execution/slippage${toQuery(args ?? {})}`),

tradeAnalytics: (args?: { start?: string; end?: string; strategy_id?: string }) =>
  get<KeyValue>(`/api/v1/analytics/trades${toQuery(args ?? {})}`),
```

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

## Phase 6: Portfolio-Level Views & Unified Dashboard

### Prompt 6.1 — Add Portfolio Query Functions

```
Read `analytics_platform/backend/api/queries.py` fully.

Add these query functions:

1. `get_portfolio_overview(conn, start: str | None = None, end: str | None = None) -> dict[str, Any]`:
   - **latest**: Get the most recent row from portfolio_snapshots (ORDER BY date_ny DESC LIMIT 1)
     Extract: date_ny, capital_total, capital_cash, capital_invested, gross_exposure, net_exposure, realized_pnl, unrealized_pnl, fees_today
   - **positions**: Get all portfolio_positions for that latest date_ny
     Compute weight_pct = notional / SUM(notional) * 100 for each position
   - **exposure_by_strategy**: GROUP BY strategy_id from portfolio_positions for latest date, SUM(notional)
   - **history**: Get all portfolio_snapshots in date range, return as time series: [{date_ny, capital_total, gross_exposure, net_exposure, realized_pnl}]
   - Return dict with keys: latest, positions, exposure_by_strategy, history

2. `get_portfolio_positions(conn, date: str | None = None) -> dict[str, Any]`:
   - If date not specified, find latest date_ny from portfolio_positions
   - Query all positions for that date
   - Compute weight_pct for each: notional / total_notional * 100
   - Group by strategy_id for easy rendering
   - Sort by notional DESC within each group
   - Return: {date_ny, total_notional, by_strategy: [{strategy_id, positions: [...]}]}

3. `get_portfolio_history(conn, start: str | None, end: str | None) -> dict[str, Any]`:
   - Select from portfolio_snapshots with date range filtering
   - Return list of {date_ny, capital_total, capital_cash, gross_exposure, net_exposure, realized_pnl, unrealized_pnl}
   - ORDER BY date_ny ASC

4. `get_strategy_matrix(conn) -> dict[str, Any]`:
   - For S1/S2: count trades from decision_intents, count unique symbols, get latest regime from regime_daily
   - For RAEC: count rebalances from raec_rebalance_events, count unique symbols from raec_intents, get latest regime
   - Get exposure from portfolio_positions (latest date, grouped by strategy_id)
   - Find symbol overlap: symbols that appear in multiple strategies
   - Return: {strategies: [...], symbol_overlap: [{symbol, strategy_ids: [...]}]}

Run: `./venv/bin/pytest tests/analytics_platform -x -v`
```

---

### Prompt 6.2 — Add Portfolio API Endpoints

```
Read `analytics_platform/backend/app.py` fully.

Add 4 new endpoints:

1. **Portfolio Overview**:
   ```python
   @app.get("/api/v1/portfolio/overview")
   def portfolio_overview(
       start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
   ) -> dict:
       runtime: AnalyticsRuntime = app.state.runtime
       with connect_ro(runtime.settings.db_path) as conn:
           payload = queries.get_portfolio_overview(conn, start, end)
       return _envelope(runtime, payload)
   ```

2. **Portfolio Positions**:
   ```python
   @app.get("/api/v1/portfolio/positions")
   def portfolio_positions(
       date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
   ) -> dict:
       runtime: AnalyticsRuntime = app.state.runtime
       with connect_ro(runtime.settings.db_path) as conn:
           payload = queries.get_portfolio_positions(conn, date)
       return _envelope(runtime, payload)
   ```

3. **Portfolio History**:
   ```python
   @app.get("/api/v1/portfolio/history")
   def portfolio_history(
       start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
   ) -> dict:
       runtime: AnalyticsRuntime = app.state.runtime
       with connect_ro(runtime.settings.db_path) as conn:
           payload = queries.get_portfolio_history(conn, start, end)
       return _envelope(runtime, payload)
   ```

4. **Strategy Matrix**:
   ```python
   @app.get("/api/v1/strategies/matrix")
   def strategy_matrix() -> dict:
       runtime: AnalyticsRuntime = app.state.runtime
       with connect_ro(runtime.settings.db_path) as conn:
           payload = queries.get_strategy_matrix(conn)
       return _envelope(runtime, payload)
   ```

Place these after the execution/analytics endpoints.

Run: `./venv/bin/pytest tests/analytics_platform -x -v`
```

---

### Prompt 6.3 — Create Portfolio Overview Page

```
Read `analytics_platform/frontend/src/pages/OverviewPage.tsx` for reference patterns.

Create `analytics_platform/frontend/src/pages/PortfolioPage.tsx`:

```tsx
import { PieChart, Pie, Cell, LineChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

const STRATEGY_COLORS: Record<string, string> = {
  S1_AVWAP_CORE: "#1f6feb",
  S2_LETF_ORB_AGGRO: "#8b5cf6",
  RAEC_401K_V1: "#0f9d58",
  RAEC_401K_V2: "#34a853",
  RAEC_401K_V3: "#dd6b20",
  RAEC_401K_V4: "#db4437",
  RAEC_401K_V5: "#f4b400",
  RAEC_401K_COORD: "#4285f4",
};

export function PortfolioPage() {
  const overview = usePolling(() => api.portfolioOverview(), 60_000);

  if (overview.loading) return <LoadingState text="Loading portfolio data..." />;
  if (overview.error) return <ErrorState error={overview.error} />;

  const data = overview.data?.data as Record<string, any> ?? {};
  const latest = data.latest ?? {};
  const positions = data.positions ?? [];
  const exposureByStrategy = data.exposure_by_strategy ?? [];
  const history = data.history ?? [];

  const formatCurrency = (val: number | null) =>
    val != null ? `$${val.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—";

  return (
    <section>
      <h2 className="page-title">Portfolio Overview</h2>

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          This page shows your <strong>unified portfolio</strong> across all strategies.
          Monitor <strong>capital utilization</strong> (cash vs. invested),
          <strong> gross/net exposure</strong>, and <strong>P&amp;L</strong> to ensure
          the portfolio is operating within risk bounds.
        </p>
      </div>

      {/* Capital KPIs */}
      <div className="kpi-grid">
        <KpiCard label="Total Capital" value={formatCurrency(latest.capital_total)} />
        <KpiCard label="Cash" value={formatCurrency(latest.capital_cash)} />
        <KpiCard label="Invested" value={formatCurrency(latest.capital_invested)} />
        <KpiCard label="Gross Exposure" value={formatCurrency(latest.gross_exposure)} />
        <KpiCard label="Net Exposure" value={formatCurrency(latest.net_exposure)} />
      </div>

      {/* P&L KPIs */}
      <div className="kpi-grid">
        <KpiCard label="Realized P&L (Today)" value={formatCurrency(latest.realized_pnl)} />
        <KpiCard label="Unrealized P&L" value={formatCurrency(latest.unrealized_pnl)} />
        <KpiCard label="Fees (Today)" value={formatCurrency(latest.fees_today)} />
      </div>

      {/* Exposure by Strategy pie chart */}
      {exposureByStrategy.length > 0 && (
        <div className="chart-card">
          <h3>Exposure by Strategy</h3>
          <div className="pie-card">
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={exposureByStrategy}
                  dataKey="notional"
                  nameKey="strategy_id"
                  cx="50%"
                  cy="50%"
                  outerRadius={100}
                  label={({ strategy_id, notional }) => `${strategy_id}: $${(notional / 1000).toFixed(0)}k`}
                >
                  {exposureByStrategy.map((entry: any, idx: number) => (
                    <Cell key={idx} fill={STRATEGY_COLORS[entry.strategy_id] ?? "#999"} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Capital over time */}
      {history.length > 0 && (
        <div className="chart-card">
          <h3>Capital & Exposure Over Time</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={history}>
              <XAxis dataKey="date_ny" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="capital_total" stroke="#1f6feb" strokeWidth={2} name="Capital" dot={false} />
              <Line type="monotone" dataKey="gross_exposure" stroke="#dd6b20" strokeWidth={1.5} name="Gross Exposure" dot={false} />
              <Line type="monotone" dataKey="net_exposure" stroke="#0f9d58" strokeWidth={1.5} name="Net Exposure" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Position table */}
      {positions.length > 0 && (
        <div className="table-card">
          <h3>All Positions ({latest.date_ny})</h3>
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Symbol</th>
                <th>Qty</th>
                <th>Avg Price</th>
                <th>Mark Price</th>
                <th>Notional</th>
                <th>Weight</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p: any, idx: number) => (
                <tr key={idx}>
                  <td>{p.strategy_id}</td>
                  <td><strong>{p.symbol}</strong></td>
                  <td>{p.qty}</td>
                  <td>{p.avg_price != null ? `$${p.avg_price.toFixed(2)}` : "—"}</td>
                  <td>{p.mark_price != null ? `$${p.mark_price.toFixed(2)}` : "—"}</td>
                  <td>{formatCurrency(p.notional)}</td>
                  <td>
                    {p.weight_pct != null ? `${p.weight_pct.toFixed(1)}%` : "—"}
                    <div className="weight-bar" style={{ width: `${Math.min(p.weight_pct ?? 0, 100)}%` }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
```

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 6.4 — Create Strategy Matrix Page

```
Read `analytics_platform/frontend/src/pages/OverviewPage.tsx` for reference.

Create `analytics_platform/frontend/src/pages/StrategyMatrixPage.tsx`:

The page should have:

1. **Helper card** — "This page compares all strategies side-by-side. Use it to identify symbol overlap, compare activity levels, and understand how each strategy contributes to overall portfolio exposure."

2. **Strategy cards grid** — One card per strategy using the `.matrix-grid` and `.matrix-card` CSS classes. Each card shows:
   - Strategy name (bold)
   - Type label: S1/S2/RAEC (using `.matrix-card.type-s1` etc.)
   - Trade count
   - Unique symbols
   - Current regime (for RAEC strategies, with regime-badge)
   - Exposure ($)

3. **Comparison table** — All strategies in one table:
   | Strategy | Type | Trades | Symbols | Regime | Exposure |

4. **Symbol overlap section** — A table showing symbols that appear in multiple strategies:
   | Symbol | Strategies | Count |
   Highlight symbols appearing in 3+ strategies in orange.

Use `api.strategyMatrix()` with usePolling at 60_000ms.

Determine strategy type from the strategy_id:
```typescript
const getType = (id: string) => {
  if (id.startsWith("S1")) return "s1";
  if (id.startsWith("S2")) return "s2";
  return "raec";
};
```

Follow the same patterns as other pages: usePolling, LoadingState, ErrorState, KpiCard grid, charts/tables.

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 6.5 — Add Phase 6 Types, API Methods, Routes, and Sidebar

```
Read these files:
- `analytics_platform/frontend/src/types.ts`
- `analytics_platform/frontend/src/api.ts`
- `analytics_platform/frontend/src/App.tsx`
- `analytics_platform/frontend/src/components/Layout.tsx`

**In types.ts**, add:
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

export interface StrategyMatrixRow {
  strategy_id: string;
  strategy_type: string;
  trade_count: number;
  unique_symbols: number;
  current_regime: string | null;
  exposure: number | null;
}

export interface SymbolOverlap {
  symbol: string;
  strategy_ids: string[];
}
```

**In api.ts**, add to the api object:
```typescript
portfolioOverview: (args?: { start?: string; end?: string }) =>
  get<KeyValue>(`/api/v1/portfolio/overview${toQuery(args ?? {})}`),

portfolioPositions: (args?: { date?: string }) =>
  get<KeyValue>(`/api/v1/portfolio/positions${toQuery(args ?? {})}`),

portfolioHistory: (args?: { start?: string; end?: string }) =>
  get<KeyValue>(`/api/v1/portfolio/history${toQuery(args ?? {})}`),

strategyMatrix: () => get<KeyValue>("/api/v1/strategies/matrix"),
```

**In App.tsx**, add imports and routes:
```tsx
import { PortfolioPage } from "./pages/PortfolioPage";
import { SlippagePage } from "./pages/SlippagePage";
import { StrategyMatrixPage } from "./pages/StrategyMatrixPage";
import { TradeAnalyticsPage } from "./pages/TradeAnalyticsPage";

// Inside <Routes>, before catch-all:
<Route path="/portfolio" element={<PortfolioPage />} />
<Route path="/execution/slippage" element={<SlippagePage />} />
<Route path="/analytics/trades" element={<TradeAnalyticsPage />} />
<Route path="/strategies/matrix" element={<StrategyMatrixPage />} />
```

**In Layout.tsx**, update NAV_SECTIONS to include the new sections:
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
    label: "Portfolio",
    items: [
      { to: "/portfolio", label: "Overview" },
      { to: "/strategies/matrix", label: "Strategy Matrix" },
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
    label: "Execution",
    items: [
      { to: "/execution/slippage", label: "Slippage" },
      { to: "/analytics/trades", label: "Trade Analytics" },
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

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 6.6 — Add Phase 5/6 CSS Styles

```
Read `analytics_platform/frontend/src/styles.css`.

Append these CSS rules at the end of the file (after the Phase 4 styles). Do NOT modify any existing styles.

```css
/* === Phase 5/6: Portfolio & Analytics Styles === */

.portfolio-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.slippage-good { color: #0f9d58; font-weight: 600; }
.slippage-warn { color: #dd6b20; font-weight: 600; }
.slippage-bad { color: #db4437; font-weight: 600; }

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

.matrix-card h4 {
  margin: 0 0 0.5rem 0;
  font-size: 0.95rem;
}

.matrix-card div {
  font-size: 0.85rem;
  margin-bottom: 0.25rem;
  color: var(--text-secondary, #a0a0b0);
}

.matrix-card.type-s1 { border-left-color: #1f6feb; }
.matrix-card.type-s2 { border-left-color: #8b5cf6; }
.matrix-card.type-raec { border-left-color: #0f9d58; }

.weight-bar {
  height: 4px;
  background: #1f6feb;
  border-radius: 2px;
  margin-top: 2px;
}

.pie-card {
  display: flex;
  justify-content: center;
  padding: 1rem;
}

.overlap-highlight {
  background: #dd6b2020;
  border-radius: 4px;
  padding: 0.1rem 0.3rem;
}

.strategy-type-badge {
  display: inline-block;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
}

.strategy-type-badge.s1 { background: #1f6feb20; color: #1f6feb; }
.strategy-type-badge.s2 { background: #8b5cf620; color: #8b5cf6; }
.strategy-type-badge.raec { background: #0f9d5820; color: #0f9d58; }
```

Run: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 6.7 — Upgrade Overview Page with Portfolio Summary

```
Read `analytics_platform/frontend/src/pages/OverviewPage.tsx`.

Add a portfolio summary section at the TOP of the page content (before existing KPIs). This section is non-blocking — if portfolio data isn't available, it's simply skipped.

1. Add a new usePolling for portfolio overview:
   ```tsx
   const portfolio = usePolling(() => api.portfolioOverview(), 60_000);
   ```

2. Add a portfolio section before the existing content, render only if data available:
   ```tsx
   {portfolio.data && !portfolio.error && (() => {
     const pData = (portfolio.data.data as Record<string, any>) ?? {};
     const latest = pData.latest ?? {};
     const fmt = (v: number | null) => v != null ? `$${v.toLocaleString(undefined, {maximumFractionDigits: 0})}` : "—";
     return (
       <div className="kpi-grid" style={{ marginBottom: "1.5rem" }}>
         <KpiCard label="Portfolio Capital" value={fmt(latest.capital_total)} />
         <KpiCard label="Net Exposure" value={fmt(latest.net_exposure)} />
         <KpiCard label="Strategies Active" value={(pData.exposure_by_strategy ?? []).length} />
         <KpiCard label="Realized P&L Today" value={fmt(latest.realized_pnl)} />
       </div>
     );
   })()}
   ```

This adds 4 KPI cards at the top of the overview for portfolio health — non-blocking and degrading gracefully if no snapshot data exists.

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 6.8 — Update Help Page with All New Pages

```
Read `analytics_platform/frontend/src/pages/HelpPage.tsx`.

Add rows to the "Page-by-Page Purpose" table for ALL new pages from Phase 5 and Phase 6:

```tsx
<tr>
  <td>Portfolio Overview</td>
  <td>Unified view of capital, exposure, positions, and P&amp;L across all strategies.</td>
  <td>Act if exposure exceeds limits, cash drops below threshold, or P&amp;L shows anomalies.</td>
</tr>
<tr>
  <td>Strategy Matrix</td>
  <td>Cross-strategy comparison with symbol overlap detection and exposure breakdown.</td>
  <td>Act if symbol overlap creates unintended concentration across strategies.</td>
</tr>
<tr>
  <td>Slippage</td>
  <td>Execution quality analysis — how actual fills compare to benchmarks, broken down by liquidity and time of day.</td>
  <td>Act if mean slippage exceeds 10 bps or shows a worsening trend.</td>
</tr>
<tr>
  <td>Trade Analytics</td>
  <td>Cross-strategy trade frequency, symbol concentration, and activity analysis.</td>
  <td>Review weekly for concentration risk or unusual trading patterns.</td>
</tr>
```

Also update the "Recommended Daily Workflow" section to include:
```tsx
<li>Start with <strong>Portfolio Overview</strong> for a unified view of capital, exposure, and P&amp;L across all strategies.</li>
<li>Check <strong>Strategy Matrix</strong> weekly to ensure no unintended symbol overlap or concentration.</li>
<li>Review <strong>Slippage</strong> weekly to monitor execution quality trends.</li>
```

Run type check: `cd analytics_platform/frontend && npx tsc --noEmit`
```

---

### Prompt 6.9 — Portfolio & Analytics Tests

```
Create `tests/analytics_platform/test_api_portfolio.py`:

Follow the same pattern: analytics_settings fixture, importorskip, build_readmodels, create_app, TestClient.

Write these tests:

1. `test_portfolio_overview(analytics_settings)`:
   - GET /api/v1/portfolio/overview
   - Assert 200, assert "latest" in data
   - Assert latest has capital_total=100000.0

2. `test_portfolio_positions(analytics_settings)`:
   - GET /api/v1/portfolio/positions
   - Assert 200, assert "by_strategy" in data or positions list exists
   - Assert at least 3 positions (AAPL, MSFT, TQQQ from fixture)

3. `test_portfolio_history(analytics_settings)`:
   - GET /api/v1/portfolio/history
   - Assert 200, assert data is a list with at least 1 entry

4. `test_strategy_matrix(analytics_settings)`:
   - GET /api/v1/strategies/matrix
   - Assert 200, assert "strategies" in data

5. `test_portfolio_exports(analytics_settings)`:
   - GET /api/v1/exports/portfolio_positions.csv
   - Assert 200, assert text/csv

Run: `./venv/bin/pytest tests/analytics_platform/test_api_portfolio.py -x -v`

---

Create `analytics_platform/frontend/src/__tests__/portfolio_pages.test.tsx`:

Write smoke tests following the same pattern as raec_pages.test.tsx:

```tsx
vi.mock("../api", () => ({
  api: {
    portfolioOverview: vi.fn().mockResolvedValue({
      data: { latest: {}, positions: [], exposure_by_strategy: [], history: [] },
    }),
    strategyMatrix: vi.fn().mockResolvedValue({
      data: { strategies: [], symbol_overlap: [] },
    }),
    slippage: vi.fn().mockResolvedValue({
      data: { summary: {}, by_bucket: [], by_time: [], by_symbol: [], trend: [] },
    }),
    tradeAnalytics: vi.fn().mockResolvedValue({
      data: { per_strategy: [], daily_frequency: [], symbol_concentration: [] },
    }),
  },
}));
```

Test that PortfolioPage, StrategyMatrixPage, SlippagePage, and TradeAnalyticsPage render without crashing (show loading state).

Run: `cd analytics_platform/frontend && npx vitest run`
```

---

### Prompt 6.10 — Final Integration Test (All 6 Phases)

```
Run the full test suite to verify all 6 phases work together:

1. Backend tests: `./venv/bin/pytest tests/analytics_platform -x -v`
2. Strategy tests (no regressions): `./venv/bin/pytest tests/ --ignore=tests/analytics_platform -x -v`
3. Frontend type check: `cd analytics_platform/frontend && npx tsc --noEmit`
4. Frontend tests: `cd analytics_platform/frontend && npx vitest run`

Fix any failures. Report final test counts and verify:
- All 21 DuckDB tables are created by build_readmodels
- All 20 API endpoints return 200
- All 15 frontend pages render without crashing
- No strategy test regressions
```

---

## Execution Summary

| Prompt | Phase | Description | Files Changed |
|--------|-------|-------------|---------------|
| 1.1 | Pipeline | Add RAEC fixtures to conftest | `tests/analytics_platform/conftest.py` |
| 1.2 | Pipeline | Add RAEC ingestion to build_readmodels | `backend/readmodels/build_readmodels.py` |
| 1.3 | Pipeline | Add RAEC readmodel tests | `tests/analytics_platform/test_readmodels_raec.py` (new) |
| 1.4 | Pipeline | Add ledger writer to RAEC strategies | `strategies/raec_401k*.py` (6 files) |
| 2.1 | API | Add RAEC query functions | `backend/api/queries.py` |
| 2.2 | API | Add RAEC API endpoints | `backend/app.py` |
| 2.3 | API | Add RAEC API tests | `tests/analytics_platform/test_api_raec.py` (new) |
| 3.1 | Frontend | Add API client methods + types | `frontend/src/api.ts`, `frontend/src/types.ts` |
| 3.2 | Frontend | Create RAEC Dashboard page | `frontend/src/pages/RaecDashboardPage.tsx` (new) |
| 3.3 | Frontend | Create Trade Journal page | `frontend/src/pages/JournalPage.tsx` (new) |
| 3.4 | Frontend | Create Readiness page | `frontend/src/pages/ReadinessPage.tsx` (new) |
| 3.5 | Frontend | Create P&L page | `frontend/src/pages/PnlPage.tsx` (new) |
| 4.1 | Integration | Update routes + sidebar | `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx` |
| 4.2 | Integration | Add new CSS styles | `frontend/src/styles.css` |
| 4.3 | Integration | Upgrade Overview page | `frontend/src/pages/OverviewPage.tsx` |
| 4.4 | Integration | Update Help page | `frontend/src/pages/HelpPage.tsx` |
| 4.5 | Integration | Frontend smoke tests | `frontend/src/__tests__/raec_pages.test.tsx` (new) |
| 4.6 | Integration | Full Phase 1-4 integration test | (verification only) |
| 5.1 | Analytics | Add analytics fixture data | `tests/analytics_platform/conftest.py` |
| 5.2 | Analytics | Add analytics ingestion to build_readmodels | `backend/readmodels/build_readmodels.py` |
| 5.3 | Analytics | Add analytics readmodel tests | `tests/analytics_platform/test_readmodels_analytics.py` (new) |
| 5.4 | Analytics | Add slippage + trade query functions | `backend/api/queries.py` |
| 5.5 | Analytics | Add execution quality API endpoints | `backend/app.py` |
| 5.6 | Analytics | Create Slippage Dashboard page | `frontend/src/pages/SlippagePage.tsx` (new) |
| 5.7 | Analytics | Create Trade Analytics page | `frontend/src/pages/TradeAnalyticsPage.tsx` (new) |
| 5.8 | Analytics | Add analytics API tests | `tests/analytics_platform/test_api_analytics.py` (new) |
| 5.9 | Analytics | Add Phase 5 types + API methods | `frontend/src/types.ts`, `frontend/src/api.ts` |
| 6.1 | Portfolio | Add portfolio query functions | `backend/api/queries.py` |
| 6.2 | Portfolio | Add portfolio API endpoints | `backend/app.py` |
| 6.3 | Portfolio | Create Portfolio Overview page | `frontend/src/pages/PortfolioPage.tsx` (new) |
| 6.4 | Portfolio | Create Strategy Matrix page | `frontend/src/pages/StrategyMatrixPage.tsx` (new) |
| 6.5 | Portfolio | Add types, API methods, routes, sidebar | `types.ts`, `api.ts`, `App.tsx`, `Layout.tsx` |
| 6.6 | Portfolio | Add Phase 5/6 CSS styles | `frontend/src/styles.css` |
| 6.7 | Portfolio | Upgrade Overview with portfolio summary | `frontend/src/pages/OverviewPage.tsx` |
| 6.8 | Portfolio | Update Help page | `frontend/src/pages/HelpPage.tsx` |
| 6.9 | Portfolio | Portfolio & analytics tests | `test_api_portfolio.py`, `portfolio_pages.test.tsx` (new) |
| 6.10 | Portfolio | Final 6-phase integration test | (verification only) |

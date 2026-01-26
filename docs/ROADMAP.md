# AVWAP Trading System — Canonical Roadmap

**Status:** ACTIVE  
**Canonical Branch:** `main`  
**Source of Truth:** This document governs scope, sequencing, and completion state.

---

## Non-Negotiable Invariants

- Determinism over convenience
- Fail-closed behavior on all safety gates
- One authoritative execution plane
- Git-first discipline (no SCP, no droplet-only edits)
- Analytics is an observability spine, not a bolt-on
- ML is advisory only, feature-flagged, and offline-validated
- Every phase must leave the system deployable and test-clean

---

## Phase A — Reliable Paper Loop

**Status:** ✅ COMPLETE

**Objective:** Prove deterministic, unattended operation without broker risk.

### Tasks
- [x] Deterministic scan → execution pipeline
- [x] DRY_RUN execution mode
- [x] Daily candidate generation
- [x] Watchlist freshness gating (NY date aware)
- [x] Slack observability for scans
- [x] Deterministic test runner (`tests/run_tests.py`)
- [x] JSON output stability (sorted keys, reproducible bytes)
- [x] CI trust checks (required docs, provenance)

---

## Phase B — Execution Safety & Live Gate

**Status:** ✅ COMPLETE

**Objective:** Make live trading possible but explicitly gated and reversible.

### Tasks
- [x] LIVE enablement via explicit confirmation token
- [x] Kill switch (hard block on new entries)
- [x] Max risk per trade (absolute + percent)
- [x] Max gross exposure (absolute + percent)
- [x] Max concurrent positions
- [x] Max new entries per day
- [x] Allowlist enforcement
- [x] Offline execution config-check command (preflight validation)
- [x] NY-date ledger rollover
- [x] Broker reconciliation discipline
- [x] Slack alerts for execution decisions

---

## Phase C — Controlled Live Trading (Single Strategy)

**Status:** ✅ COMPLETE

**Objective:** Allow *exactly one* strategy to trade live under strict control.

### Tasks
- [x] Phase-C enable date gate
- [x] Single-symbol allowlist enforcement
- [x] Explicit rejection on mismatched date or symbol
- [x] Phase-C bypass leaves Phase-B behavior unchanged
- [x] Deterministic tests for all Phase-C gates

---

## Phase C′ — System-Managed Exits (Structural Risk Control)

**Status:** ✅ COMPLETE

**Objective:** Remove discretionary exits and enforce structural risk discipline.

### Tasks
- [x] Intraday higher-low structural stops
- [x] Daily swing-low fallback stops
- [x] Trailing stop ratchet (risk never loosens)
- [x] Time-gated stop submission
- [x] Persistent per-symbol position state
- [x] Broker stop reconciliation
- [x] Exit logic invoked every execution cycle
- [x] Deterministic exit behavior tests
- [x] Live deployment verified on droplet

---

## Phase D — Portfolio, Allocation, and Analytics Layer

> Phase D turns the system from a **trade executor** into a **portfolio manager**.
> No new alpha is introduced here — only measurement, allocation, and control.

---

## Phase D0 — Portfolio & Analytics Data Contracts

**Status:** ✅ COMPLETE

**Objective:** Establish immutable, deterministic data contracts.

### Tasks
- [x] Canonical schemas for entries and fills
- [x] Deterministic ledger parsing
- [x] Stable hash-based IDs (orders, positions)
- [x] Canonical exit event schema
- [x] Position ↔ trade ↔ exit linkage
- [x] Exit telemetry ingestion layer
- [x] Schema validation tests

---

## Phase D1 — Exit Observability & Trade Reconstruction

**Status:** ✅ COMPLETE

**Objective:** Make exits measurable, replayable, and analyzable.

### Tasks
- [x] Structured exit event emission
- [x] MAE / MFE computation per trade
- [x] Stop efficiency metrics
- [x] Broker-independent exit simulator
- [x] Deterministic trade reconstruction from real exits
- [x] Exit parity tests (real vs simulated)
- [x] Exit metrics persistence
- [x] Droplet validation

---

## Phase D2 — Intelligent Allocation & Core Portfolio Metrics

**Status:** ✅ COMPLETE

**Objective:** Decide *how much* to trade each signal and *how to size the portfolio*.

### Tasks
- [x] Define canonical **Portfolio Snapshot** schema
  - capital
  - gross exposure
  - net exposure
  - open positions
- [x] Compute realized PnL (net of fees)
- [x] Compute unrealized PnL
- [x] Compute drawdown (peak-to-trough)
- [x] Compute rolling volatility of returns
- [x] Per-symbol contribution analysis
- [x] Deterministic daily portfolio snapshot writer
- [x] Capital-aware position sizing function
- [x] Allocation guardrails (concentration, correlation placeholder)
- [x] Deterministic serialization + ordering
- [x] Unit tests for all portfolio metrics
- [x] No changes to signal generation (measurement only)

**Exit Criteria**
- Daily portfolio snapshot written deterministically
- Metrics reproducible byte-for-byte
- All tests pass locally and on droplet

---

## Phase D3 — Deterministic Reporting & Ops Integration

**Status:** ✅ COMPLETE

**Objective:** Make portfolio state human-auditable and operator-friendly.

### Tasks
- [x] D3.1 — Broker adapter (read-only, Alpaca-first)
- [x] D3.2 — Canonical reconciliation schema
- [x] D3.3 — Reconciliation engine + deterministic report artifact
- [x] D3.4 — Daily portfolio snapshot runner + artifact pathing
- [x] D3.5 — Offline tests + registry updates

---

## Phase 2 — Portfolio Decision Layer

> Phase 2 computes deterministic portfolio decisions from Phase D artifacts.
> Shadow mode only in Phase 2A: no execution impact.

---

## Phase 2A — Shadow Decisions

**Status:** ✅ COMPLETE

**Objective:** Emit deterministic, auditable ALLOW/BLOCK portfolio decisions without execution changes.

### Tasks
- [x] Canonical PortfolioDecision + PortfolioDecisionBatch schemas
- [x] Deterministic decision engine (ALLOW/BLOCK only)
- [x] Guardrails: max open positions, max new entries/day, symbol concentration, gross exposure, drawdown throttle
- [x] Deterministic artifact writer (analytics/artifacts/portfolio_decisions/YYYY-MM-DD.json)
- [x] Fail-closed handling for missing candidates and portfolio snapshots
- [x] Offline fixture-based tests + registry updates
- [x] Shadow strategy cloning + arbiter rejection for S2-era multi-strategy validation

## Phase 2B — Enforcement (COMPLETE)

**Status:** ✅ COMPLETE

**Objective:** Enforce Phase 2A ALLOW/BLOCK decisions for new entries (exits never blocked), behind an explicit feature flag, with fail-closed behavior and offline deterministic tests.

### Tasks
- [x] Add feature flag `PORTFOLIO_DECISION_ENFORCE=1` (default OFF)
- [x] Add decision reader + schema validation for `analytics/artifacts/portfolio_decisions/YYYY-MM-DD.json`
- [x] Enforce ALLOW/BLOCK for **new entries only** in the execution layer (no alpha changes)
- [x] Fail-closed: missing/invalid/mismatched-date decision artifact → BLOCK new entries with explicit reason codes
- [x] Deterministic enforcement telemetry artifact (append-only JSONL) with provenance + reason codes
- [x] Slack operator alert summarizing blocked entries when enforcement is enabled
- [x] Offline fixture-based tests for all enforcement paths; register in `tests/run_tests.py`
- [x] Runbook update: how to enable/disable, expected fail-closed behavior, artifact locations

**Exit Criteria**
- Enforcement is reversible (flagged), deterministic, and fail-closed
- Exits remain unaffected
- All tests pass on Mac + droplet


---

## Phase M1-A — Book Plumbing & Ledger Routing (NO behavior change)

**Status:** ✅ COMPLETE

**Objective:** Introduce `book_id` plumbing and book-scoped ledger routing without altering existing Alpaca behavior.

### Tasks
- [x] Define explicit `book_id` constants (ALPACA_PAPER, ALPACA_LIVE, SCHWAB_401K_MANUAL)
- [x] Add `book_id` to Alpaca ledger records (append-only JSONL)
- [x] Route Alpaca ledgers to `ledger/<book_id>/<YYYY-MM-DD>.jsonl`
- [x] Adapter selection keyed by `book_id` with Schwab placeholder
- [x] Routing invariant test for Schwab (no Alpaca imports)
- [x] Documentation for `book_id` and ledger paths

---

### Phase M1-B — Schwab Manual Slack Ticket Adapter (Outbound Only)

**Status:** ✅ COMPLETE

**Objective:**  
Allow the Schwab 401(k) book to emit **human-executable trade tickets** via Slack,
with deterministic idempotency and append-only intent tracking.

**Tasks**
- [x] Implement Slack Ticket execution adapter for `SCHWAB_401K_MANUAL`
- [x] Deterministic `intent_id` function (hash-based)
- [x] Idempotency: prevent duplicate Slack posts per as-of date
- [x] Append-only ledger entries for SENT intents (with Slack metadata)
- [x] Adapter selection wiring (Schwab → Slack, Alpaca unchanged)
- [x] Guarded CLI smoke runner (env-protected Slack posting)
- [x] Offline deterministic tests (mock Slack)

**Exit Criteria**
- Slack tickets post deterministically
- Re-runs do not duplicate tickets
- Alpaca paths unaffected
- Tests pass

---

### Phase M1-C — Slack Reply Ingestion & Confirmation Ledger

**Status:** ✅ COMPLETE

**Objective:**  
Close the loop for manual execution by ingesting Slack replies and recording confirmations
(EXECUTED / PARTIAL / SKIPPED / ERROR) in the Schwab ledger.

**Tasks**
- [x] Minimal Slack Events receiver (signature verification + URL challenge)
- [x] Scope enforcement: channel + threaded replies only
- [x] Robust parser for confirmation lines
- [x] Append-only confirmation records (no mutation)
- [x] Graceful handling of unmatched intent IDs
- [x] Event dedupe for Slack retries
- [x] Unit tests for parser + handler
- [x] Operator documentation for running the service

**Exit Criteria**
- Slack replies update Schwab ledger deterministically
- Confirmations are auditable and append-only
- Tests pass

---
## Phase M1-D — Schwab Read-Only Account Snapshot & Reconciliation

**Status:** ✅ COMPLETE

**Objective:**  
Ingest Schwab PCRA broker-truth data in **read-only** mode and reconcile it against
manual trade intents (M1-B) and confirmations (M1-C), without impacting execution
or portfolio decisions.

### Tasks
- [x] Define canonical read-only broker snapshot schemas (balances, positions, orders)
- [x] Implement fixture-backed Schwab read-only adapter (no live calls)
- [x] OAuth scaffolding (env-only, feature-flagged, no execution wiring)
- [x] Deterministic account snapshot writer (append-only)
- [x] Reconciliation engine: intents vs confirmations vs broker truth
- [x] Drift detection (partial fills, missing executions, qty mismatches)
- [x] Snapshot + reconciliation analytics integration (measurement-only)
- [x] Offline deterministic unit tests (fixtures only)
- [x] Operator documentation for read-only ingestion

**Constraints**
- Read-only only (no order placement, no execution side effects)
- Default OFF behind feature flag
- No imports into `execution_v2`
- No network calls in unit tests
- Append-only storage only

**Exit Criteria**
- Broker snapshots are ingested deterministically
- Reconciliation outputs are auditable and append-only
- Alpaca and execution paths remain unchanged
- All tests pass offline on Mac and droplet


## Phase E1 — Regime Detection (Measurement Only)

**Status:** ✅ COMPLETE

**Objective:**  
Detect and classify market regimes using offline data, producing **descriptive**
regime signals without impacting risk, portfolio decisions, or execution.

### Tasks
- [x] Define regime taxonomy (e.g., risk-on, risk-off, neutral, stressed)
- [x] Select allowable regime inputs (volatility, breadth, drawdown, trend)
- [x] Implement deterministic regime classifiers (no ML, no adaptation)
- [x] Persist regime outputs as append-only analytics artifacts
- [x] Historical regime labeling for backtests
- [x] Offline validation against historical periods
- [x] Unit tests for regime classification determinism

**Constraints**
- Measurement-only (no execution or portfolio effects)
- Deterministic inputs and outputs
- Offline data only
- Append-only storage

**Exit Criteria**
- Regime labels are reproducible across runs
- No downstream system behavior is modified
- Offline tests validate stability and correctness


### Phase E1.2 — Universe Network Guardrails

**Status:** ✅ COMPLETE

**Objective:**  
Guarantee universe metrics never trigger network calls when offline or in dev.

### Tasks
- [x] Add runtime `UNIVERSE_ALLOW_NETWORK` override (env-first)
- [x] Fail-closed `get_universe_metrics` guard before yfinance import
- [x] Skip metrics provider in universe rules when network is disallowed
- [x] Deterministic warning log for `universe_network_disallowed`
- [x] Tests proving yfinance is not imported when disallowed


### Phase E1.3 — Offline Universe Metrics Contract

**Status:** ✅ COMPLETE

**Objective:**  
Provide deterministic, explainable offline behavior without filtering.

### Tasks
- [x] Preserve fail-open semantics when metrics are skipped
- [x] Tests confirming provider is never invoked offline


## Phase E2 — Regime-Based Risk Modulation (No Signal Changes)

**Status:** ✅ COMPLETE

**Objective:**  
Modulate **risk parameters only** based on detected regimes, without altering
signals, symbol selection, or exit logic.

### Tasks
- [x] Define allowable risk controls (sizing multipliers, exposure caps, throttles)
- [x] Map regimes to risk multipliers deterministically
- [x] Integrate regime outputs with portfolio decision layer
- [x] Enforce feature-flagged activation (default OFF)
- [x] Drawdown-aware interaction with existing portfolio guardrails
- [x] Offline portfolio simulations with and without modulation
- [x] Deterministic tests proving signals remain unchanged

**Constraints**
- Signals and entries remain unchanged
- Exits are never blocked or modified
- Feature-flagged and reversible
- Offline validation only

**Exit Criteria**
- Risk modulation applies only when explicitly enabled
- Portfolio decisions remain deterministic
- Backtests demonstrate controlled risk impact
- All tests pass with feature flag ON and OFF

---

# PHASE S — MULTI-STRATEGY ORCHESTRATION (STRUCTURAL ONLY)

**Status:** ⏭️ FUTURE (NOT STARTED)

**Purpose:**  
Evolve the system from a *single-strategy executor* into a **portfolio of heterogeneous strategies**, governed by centralized risk, deterministic arbitration, and explicit capital partitioning — **without introducing new alpha, ML, or optimization logic**.

Phase S defines *where strategies live*, *how they interact*, and *how capital is shared*.  
It does **not** define *what signals are generated*.

---

## Phase S — Non-Negotiable Principles

- Strategies emit **intents**, never orders
- A single **Control Plane** remains authoritative for:
  - capital allocation
  - approvals / rejections
  - execution
- Cross-strategy exposure is:
  - visible
  - capped
  - attributable
- Phase S introduces **structure, not intelligence**
- No ML, no regime logic changes, no signal changes

---

## Phase S0 — Strategy Identity & Contracts

**Objective:**  
Introduce explicit, first-class **strategy identity** across the entire system.

### Tasks
- [ ] Define canonical `StrategyID` registry (e.g. `S1_AVWAP_CORE`)
- [ ] Define **Strategy Metadata Contract**:
  - strategy_id
  - asset universe
  - holding horizon
  - execution style
  - risk profile (directional / neutral / convex)
- [ ] Persist `strategy_id` on:
  - trade intents
  - orders
  - positions
  - fills
  - portfolio snapshots
- [ ] Deterministic validation tests for identity propagation

**Exit Criteria**
- Every trade, position, and PnL unit is strategy-addressable
- No anonymous or unscoped trades exist

---

## Phase S1 — Trade Intent Contract & Control-Plane Arbitration

**Objective:**  
Formalize the **Strategy → Control Plane** interface.

### Tasks
- [x] Define canonical **TradeIntent schema** (append-only):
  - strategy_id
  - symbol
  - side
  - intended notional / risk
  - stop / exit plan
  - time_in_force
  - thesis / tags
  - model_version + data_version
- [x] Control Plane arbitration logic:
  - approve / reject / resize intents
  - deterministic reason codes
- [x] Intent → decision → order lineage
- [x] Idempotency + rejection tests
- [x] Phase S1.1: corrected portfolio decision persistence (append-only ledger + latest pointer)
- [x] Phase S1.2: added portfolio decision build provenance, arbiter error context, and manual fail-closed guards

**Constraints**
- No strategy may bypass Phase B / Phase C safety gates
- No strategy may mutate capital state directly

---

## Phase S2 — Strategy Sleeves & Capital Partitioning

**Objective:**  
Introduce **strategy-scoped risk budgets** inside a unified portfolio.

### Tasks
- [x] Define **strategy sleeves**:
  - max daily loss
  - max gross exposure
  - max concurrent positions
- [x] Portfolio-level aggregation:
  - cross-strategy exposure
  - overlapping symbol risk
- [x] Deterministic enforcement:
  - per-strategy caps
  - portfolio caps
- [x] Attribution extensions:
  - PnL by strategy
  - drawdown by strategy
  - exposure by strategy

**Exit Criteria**
- Strategies cannot crowd capital implicitly
- Strategy totals reconcile exactly to portfolio totals

**Implementation Notes**
- Sleeve config is loaded via `S2_SLEEVES_JSON` (JSON mapping by `strategy_id`) or `S2_SLEEVES_FILE` (path to JSON).
- Missing sleeves for strategies with open positions or entry intents block entries unless `S2_ALLOW_UNSLEEVED=1`.
- Overlapping symbol entries are blocked by default when a symbol is already held by another strategy; set `S2_ALLOW_SYMBOL_OVERLAP=1` to allow.
- Daily loss checks use `S2_DAILY_PNL_JSON` (per-strategy PnL). Missing PnL for a capped strategy blocks entries.
- Portfolio decisions ledger includes `sleeves` config snapshot and `s2_enforcement` summaries (bounded).
- Attribution now includes per-strategy exposure, realized/unrealized PnL, and drawdown with reconciliation to portfolio totals.

---

## Phase S3 — Cross-Strategy Conflict Resolution

**Objective:**  
Prevent unintended exposure amplification when strategies collide.

### Tasks
- [ ] Detect symbol overlap across strategies
- [ ] Deterministic conflict rules:
  - priority ordering
  - offsetting / netting behavior
- [ ] Portfolio-aware resizing when overlaps occur
- [ ] Conflict reason-codes persisted

**Constraints**
- No alpha judgment
- No signal ranking
- Static, rule-based resolution only

---

## Phase S4 — Strategy-Level Attribution & Diagnostics

**Objective:**  
Make multi-strategy behavior **fully explainable**.

### Tasks
- [ ] Daily attribution by:
  - strategy
  - symbol
  - sleeve
- [ ] Strategy contribution to:
  - portfolio PnL
  - drawdown
  - volatility
- [ ] Deterministic diagnostics artifacts:
  - “which strategy caused what?”

**Exit Criteria**
- Any portfolio outcome can be decomposed by strategy
- Diagnostics are ledger-backed and reproducible

---

## Phase S — Global Constraints

- No new alpha
- No ML or optimization
- No regime logic changes
- Offline-safe, deterministic
- Fail-closed on execution, fail-open on analytics
- Ledger-backed artifacts only

---

## Dependency Position

Phase S must complete **before**:
- Phase F — ML & Causal Modules
- Activation of additional live strategies

Phase S consumes:
- Phase D portfolio snapshots
- Phase 2 portfolio decisions
- Phase E risk modulation (constraints only)

---

**Rationale:**  
Phase S is the structural layer that allows additional strategies and future ML to be *scoped, attributable, kill-switchable, and safe*. Skipping Phase S would force future intelligence to entangle with execution, sizing, and risk — exactly what the architecture is designed to avoid.



## Phase E3 — Risk Attribution & Explainability (Measurement Only)

> Phase E3 explains *why* risk was modulated.
> It introduces **no new alpha** and **no execution changes**.
> All behavior remains deterministic, offline-safe, and feature-flagged.

---

## Phase E3.1 — Risk Attribution Events (Per-Decision, Write-Only)

**Status:** ✅ COMPLETE

**Objective:**  
Produce deterministic, audit-grade explanations for any E2-driven sizing modulation
*per symbol, per decision*, without affecting signals, entries, or exits.

### Tasks
- [x] Define canonical **Risk Attribution Event** schema (append-only JSON)
  - baseline qty / notional
  - modulated qty / notional
  - delta (absolute + percent)
  - regime code + throttle policy reference
  - drawdown guard contribution (if any)
  - hard caps applied (if any)
  - ordered reason codes
- [x] Implement `analytics/risk_attribution.py`
  - deterministic event builder (pure function)
  - stable hash–based `decision_id`
  - deterministic ordering of components and reason codes
- [x] Integrate attribution writes into:
  - `backtest_engine.py` (offline)
  - `execution_v2/buy_loop.py` (runtime)
- [x] Fail-open analytics behavior:
  - attribution failures must never block execution
  - failures logged explicitly
- [x] Feature flag `E3_RISK_ATTRIBUTION_WRITE=0` (default OFF)
- [x] Unit tests proving:
  - determinism
  - no network imports
  - no behavior changes to sizing logic
- [x] Register tests in `tests/run_tests.py`

**Constraints**
- Measurement only (no execution impact)
- Offline-safe (no network calls)
- Append-only ledgers
- Deterministic byte-for-byte outputs

**Exit Criteria**
- Attribution events written deterministically when enabled
- Baseline vs modulated deltas explainable per decision
- All tests pass on Mac and droplet

---

## Phase E3.2 — Daily Aggregation & Portfolio-Level Attribution

**Status:** ✅ COMPLETE

**Objective:**  
Summarize E3.1 attribution events into deterministic, human-auditable daily artifacts.

### Tasks
- [x] Define daily attribution summary schema:
  - total baseline notional vs modulated notional
  - net exposure delta
  - count of modulated vs unmodified decisions
  - breakdown by reason code
  - top symbols by notional reduction
- [x] Implement deterministic aggregation job
- [x] Write daily summary artifact to:
  - `ledger/PORTFOLIO_RISK_ATTRIBUTION_SUMMARY/YYYY-MM-DD.json`
- [x] Ensure aggregation is reproducible from raw events
- [x] Unit tests for aggregation determinism
- [x] Feature flag `E3_RISK_ATTRIBUTION_SUMMARY_WRITE=0` (default OFF)

**Constraints**
- Derived data only (no new decisions)
- Deterministic ordering and serialization
- Offline-safe

**Exit Criteria**
- Daily summaries reproducible from raw attribution events
- Aggregates match per-decision data exactly
- Tests pass locally and on droplet

---

## Phase E3.2b — Temporal Risk Attribution Aggregation (Analytics Only)

**Status:** ✅ COMPLETE

**Objective:**  
Derive deterministic, multi-day views of risk attribution behavior to expose
*persistence*, *dominance*, and *temporal structure* in E2-driven risk modulation,
without introducing operator outputs or execution coupling.

This phase exists solely to enrich the analytics substrate consumed by
Phase E3.3 (Operator Reporting).

### Tasks
- [x] Define canonical rolling-window attribution schema (derived-only)
  - window length (e.g., 5D / 20D / 60D)
  - cumulative baseline vs modulated notional
  - persistent throttle / reason-code dominance
  - regime prevalence over window
  - top symbols by cumulative notional suppression
- [x] Implement deterministic rolling aggregation job
  - source data: `PORTFOLIO_RISK_ATTRIBUTION_SUMMARY/YYYY-MM-DD.json`
  - no direct dependency on execution or strategy logic
- [x] Write windowed artifacts to:
  - `ledger/PORTFOLIO_RISK_ATTRIBUTION_ROLLING/<WINDOW>/<YYYY-MM-DD>.json`
- [x] Feature flag `E3_RISK_ATTRIBUTION_ROLLING_WRITE=0` (default OFF)
- [x] Deterministic ordering, rounding, and serialization
- [x] Unit tests validating:
  - byte-for-byte reproducibility
  - correct handling of missing / partial windows
  - window rule: last 20 available daily summary dates on disk <= as-of

**Notes**
- Gated by `E3_RISK_ATTRIBUTION_ROLLING_WRITE=0` (default OFF)
- Output path: `ledger/PORTFOLIO_RISK_ATTRIBUTION_ROLLING/20D/YYYY-MM-DD.json`
- Window rule: last 20 available daily summary dates on disk <= as-of

**Constraints**
- Analytics-only (no operator output, no Slack)
- Derived data only (no new decisions)
- Offline-safe and deterministic
- Fail-open (missing inputs → no artifact, no error)

**Exit Criteria**
- Rolling summaries reproducible from daily summaries
- Temporal aggregates match daily data exactly
- No execution, sizing, or reporting side effects
- Tests pass locally and on droplet


---

## Phase E3.3 — Operator Reporting (Shadow Visibility Only)

**Status:** ✅ COMPLETE

**Objective:**  
Expose risk attribution insights to the operator without affecting execution.

### Tasks
- [x] Add optional Slack summary (daily):
  - headline exposure reduction
  - dominant regime + reason codes
  - count of affected symbols
- [x] Feature flag `E3_RISK_ATTRIBUTION_SLACK_SUMMARY=0` (default OFF)
- [x] Ensure Slack output is sourced only from deterministic ledger artifacts
- [x] Operator-facing language (explanatory, not prescriptive)

**Constraints**
- Shadow-only (no control surface)
- No execution coupling
- Fully reversible

**Exit Criteria**
- Slack summaries match ledger data
- Enabling/disabling has no trading impact
- Tests validate summary formatting

---

## Phase E3.4 — Activation Support & Diagnostics (Optional)

**Status:** ❌ DEFERRED

**Objective:**  
Provide diagnostics and confidence tooling *if* E2 is ever enabled beyond shadow mode.

### Tasks (Future)
- [ ] Compare realized vs hypothetical exposure deltas
- [ ] Attribution-aware performance diagnostics
- [ ] Operator review workflows

**Constraints**
- No automatic control changes
- Advisory only

---

## Phase E3.5 — Ledger Integrity Hardening (Crash-Safe Writes)

**Status:** ✅ COMPLETE

**Objective:**  
Harden critical non-append ledgers with atomic write + rename semantics.

### Tasks
- [x] Add atomic write helper (temp file + `fsync` + `os.replace` + best-effort dir `fsync`)
- [x] Apply atomic writes to dry-run idempotency ledger and live caps snapshot ledger
- [x] JSONL append-only ledgers (exit events, portfolio decisions, etc.) — **deferred intentionally**

## Phase F — ML & Causal Modules (Advisory Only)

**Status:** ❌ DEFERRED

**Objective:** Inform humans, never auto-trade.

### Tasks (Future)
- [ ] Feature store (offline)
- [ ] Label leakage controls
- [ ] Advisory scoring only
- [ ] No execution hooks
- [ ] Explicit operator opt-in

---

## Phase G — Operations, Auditing, and Lifecycle

**Status:** ❌ DEFERRED

**Objective:** Make the system sale-, audit-, and handoff-ready.

### Tasks (Future)
- [ ] Full runbook coverage
- [ ] Disaster recovery plan
- [ ] Immutable audit trails
- [ ] Versioned strategy rulesets
- [ ] Decommission / rollback playbooks

---

## Codex Instruction (MANDATORY)

Every Codex run **must**:
1. Treat this file as canonical
2. Operate on a single Phase only
3. Update task checkboxes it completes
4. Refuse to implement out-of-scope items
5. Leave the system test-clean and deployable

Failure to update this roadmap is a failed implementation.

---

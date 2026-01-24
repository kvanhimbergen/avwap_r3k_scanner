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

**Status:** ⏭️ NEXT (NOT STARTED)

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

**Status:** ⏭️ NOT STARTED

**Objective:**  
Detect and classify market regimes using offline data, producing **descriptive**
regime signals without impacting risk, portfolio decisions, or execution.

### Tasks
- [ ] Define regime taxonomy (e.g., risk-on, risk-off, neutral, stressed)
- [ ] Select allowable regime inputs (volatility, breadth, drawdown, trend)
- [ ] Implement deterministic regime classifiers (no ML, no adaptation)
- [ ] Persist regime outputs as append-only analytics artifacts
- [ ] Historical regime labeling for backtests
- [ ] Offline validation against historical periods
- [ ] Unit tests for regime classification determinism

**Constraints**
- Measurement-only (no execution or portfolio effects)
- Deterministic inputs and outputs
- Offline data only
- Append-only storage

**Exit Criteria**
- Regime labels are reproducible across runs
- No downstream system behavior is modified
- Offline tests validate stability and correctness


## Phase E2 — Regime-Based Risk Modulation (No Signal Changes)

**Status:** ⏭️ NOT STARTED

**Objective:**  
Modulate **risk parameters only** based on detected regimes, without altering
signals, symbol selection, or exit logic.

### Tasks
- [ ] Define allowable risk controls (sizing multipliers, exposure caps, throttles)
- [ ] Map regimes to risk multipliers deterministically
- [ ] Integrate regime outputs with portfolio decision layer
- [ ] Enforce feature-flagged activation (default OFF)
- [ ] Drawdown-aware interaction with existing portfolio guardrails
- [ ] Offline portfolio simulations with and without modulation
- [ ] Deterministic tests proving signals remain unchanged

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

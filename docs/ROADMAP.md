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
- [ ] Define canonical **Portfolio Snapshot** schema
  - capital
  - gross exposure
  - net exposure
  - open positions
- [ ] Compute realized PnL (net of fees)
- [ ] Compute unrealized PnL
- [ ] Compute drawdown (peak-to-trough)
- [ ] Compute rolling volatility of returns
- [ ] Per-symbol contribution analysis
- [ ] Deterministic daily portfolio snapshot writer
- [ ] Capital-aware position sizing function
- [ ] Allocation guardrails (concentration, correlation placeholder)
- [ ] Deterministic serialization + ordering
- [ ] Unit tests for all portfolio metrics
- [ ] No changes to signal generation (measurement only)

**Exit Criteria**
- Daily portfolio snapshot written deterministically
- Metrics reproducible byte-for-byte
- All tests pass locally and on droplet

---

## Phase D3 — Deterministic Reporting & Ops Integration

**Status:** ❌ NOT STARTED

**Objective:** Make portfolio state human-auditable and operator-friendly.

### Tasks
- [ ] Daily portfolio summary artifact
- [ ] Parity report: scan vs backtest vs live
- [ ] Operator-readable markdown/JSON reports
- [ ] Slack daily summary (read-only)
- [ ] Provenance embedded in all reports
- [ ] Zero new execution side-effects
- [ ] Deterministic report regeneration

---

## Phase E — Regime Layer (Risk Modulation Only)

**Status:** ❌ DEFERRED

**Objective:** Adjust risk, not signals, based on market regime.

### Tasks (Future)
- [ ] Volatility regime classifier
- [ ] Risk-on / risk-off multiplier
- [ ] Drawdown-aware throttling
- [ ] Feature-flagged activation
- [ ] Offline validation only

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

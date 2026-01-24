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

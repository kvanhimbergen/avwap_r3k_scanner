# AVWAP Trading System — Canonical Roadmap

**Status:** ACTIVE  
**Canonical Branch:** `main`  
**Source of Truth:** This document

---

## Non-Negotiable Invariants

- Determinism over convenience
- Fail-closed behavior on all safety gates
- One authoritative execution plane
- Git-first discipline (no SCP, no droplet-only edits)
- Analytics is an observability spine, not a bolt-on
- ML is advisory only, feature-flagged, and offline-validated

---

## Phase A — Reliable Paper Loop

**Status:** ✅ COMPLETE

**Objective:** Prove deterministic, unattended operation without broker risk.

### Tasks
- [x] Deterministic scan → execution pipeline
- [x] DRY_RUN execution mode
- [x] Daily candidate generation
- [x] Watchlist freshness gating
- [x] Slack observability for scans
- [x] Deterministic test runner (`tests/run_tests.py`)
- [x] JSON output stability (sorted keys, reproducible bytes)

---

## Phase B — Execution Safety & Live Gate

**Status:** ✅ COMPLETE

**Objective:** Make live trading possible but explicitly gated.

### Tasks
- [x] LIVE enablement via explicit config gates
- [x] Kill switch
- [x] Hard capital caps
- [x] Allowlist enforcement
- [x] NY-date ledger rollover
- [x] Broker reconciliation discipline
- [x] Slack alerts for execution decisions

---

## Phase C — Controlled Live Trading (Single Strategy)

**Status:** ✅ COMPLETE

---

## Phase C′ — System-Managed Exits (Structural Risk Control)

**Status:** ✅ COMPLETE

### Tasks
- [x] Intraday higher-low structural stops
- [x] Daily swing-low fallback stops
- [x] Trailing stop ratchet (risk never loosens)
- [x] Time-gated stop submission
- [x] Persistent per-symbol position state
- [x] Broker stop reconciliation
- [x] Exit logic invoked every execution cycle
- [x] Deterministic tests for exit behavior
- [x] Live deployment verified

---

## Phase D — Portfolio, Allocation, and Analytics Layer

> Phase D is where the system becomes a portfolio manager rather than a trade executor.

---

## Phase D0 — Portfolio & Analytics Data Contract

**Status:** 🟡 PARTIALLY COMPLETE

### Tasks
- [x] Canonical schemas for entries and fills
- [x] Deterministic ledger parsing
- [x] Stable hash-based IDs (entries)
- [ ] Canonical exit event schema
- [ ] Position / trade ID linkage
- [ ] Exit telemetry ingestion

---

## Phase D1 — Exit Observability & Trade Reconstruction

**Status:** ⏭️ NEXT

### Tasks
- [ ] Structured exit events
- [ ] MAE / MFE computation
- [ ] Stop efficiency metrics
- [ ] Broker-independent exit simulation
- [ ] Trade reconstruction from real exits

---

## Phase D2 — Intelligent Allocation + Core Metrics

**Status:** ❌ NOT STARTED

---

## Phase D3 — Deterministic Reporting & Ops Integration

**Status:** ❌ NOT STARTED

---

## Phase E — Regime Layer

**Status:** ❌ DEFERRED

---

## Phase F — ML & Causal Modules

**Status:** ❌ DEFERRED

---

## Phase G — Operations & Model Lifecycle

**Status:** ❌ DEFERRED

---

## Codex Instruction (Mandatory)

Any Codex prompt must treat this file as canonical and update task checkboxes as work is completed.

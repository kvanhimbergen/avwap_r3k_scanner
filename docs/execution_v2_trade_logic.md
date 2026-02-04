# Execution V2 – Trade Logic Specification

## Purpose

This document describes the implemented trade logic for Execution V2.
It reflects the current system behavior and is intended for:
- operational clarity
- auditability
- future maintenance

The authoritative source of intent remains the Execution V2 PRD.
This document documents *how that intent is realized in the system*.

---

## Strategy Scope

- Asset class: US equities
- Direction: Long-only
- Holding period: Swing / multi-day
- Style: Breakout-and-Hold (BOH)
- Execution philosophy: durability over optimization

---

## High-Level Trade Flow

1. Candidate identified externally (daily scan)
2. Candidate tracked with expiration window
3. Trade eligibility gated by:
   - global market regime
   - symbol-level regime
4. Entry requires confirmed BOH behavior
5. Entry execution is delayed and randomized
6. Risk is managed behaviorally, not via fixed stops
7. Partial exits are conditional and stateful
8. Full exit occurs only via invalidation

---

## Regime Gating

### Global Regime

Global regime determines whether new risk may be taken.

Possible states:
- OFF: no new entries
- DEFENSIVE: no new entries; exits only
- NORMAL: full execution allowed

Global regime is evaluated independently of symbol conditions.

### Symbol Regime

Each symbol is independently gated.

Possible states:
- ENTER: fresh entries allowed
- ADD: adds allowed (future use)
- HOLD_ONLY: no new risk

Symbol regime is evaluated using structural context only.
No relative strength or index comparison is used.

---

## Entry Logic

### Trigger Level

- Scan-provided `Entry_Level` from the daily candidate file (derived from AVWAP context)
- No pullback entries are allowed

### Confirmation (BOH – Option 2)

Entry requires:
1. A closed 10-minute bar closing *above* the pivot level
2. The subsequent closed 10-minute bar must *not* close back below the pivot

Both bars must be fully closed.
No intrabar evaluation is used.

### Entry Scheduling

- Entry is not immediate
- A randomized delay is applied after confirmation
- Delay is bounded and non-deterministic

Purpose:
- reduce predictability
- reduce marginalization
- avoid crowding effects

---

## Position Sizing

- Position size is determined via a volatility proxy (`Entry_DistPct`)
- A hard account-level cap is enforced

Sizing is evaluated only at entry.

---

## Risk Management (Execution)

- Initial orders are submitted as Alpaca bracket orders.
- The scan provides a structural stop (`Stop_Loss`) and a primary target (`Target_R2`).
- Behavioral stop escalation is planned but not yet automated.

### Session-phase stop authority

- OPEN_NOISE (09:30–09:45 ET): no intraday HL or new trailing; prefer daily swing low.
- EARLY_TREND (09:45–10:30 ET): daily swing low first, intraday HL only after guardrails.
- NORMAL_SESSION (10:30–15:30 ET): intraday HL primary, daily swing low fallback.
- CLOSE_PROTECT (15:30–16:00 ET): keep existing stop; no new structure-based stops.

### Guardrails

- MIN_STOP_PCT (1.5%) enforces a minimum distance from entry.
- MIN_STOP_DELAY_SECONDS (20m) and MIN_BARS_SINCE_ENTRY (4) gate intraday HL usage.

---

## Partial Exits (Conditional Trims)

- Trim logic is automated using scan-provided levels:
  - `Target_R1` triggers a partial trim (default 50%).
  - `Target_R2` triggers a second trim (default 50%).
- Trims are stateful and only fire once per level.

---

## Full Exit Logic

- Initial bracket stop orders handle early exits.
- After R2, a trailing stop (measured off the R2 move) will trigger a full exit if price reverses.

---

## Execution Guarantees

- All orders are idempotent
- State is persisted across restarts
- Duplicate orders are prevented
- Execution is single-writer and restart-safe

---

## Explicit Non-Features

Execution V2 explicitly does NOT include:

- Pullback buying
- Relative strength indicators
- Index comparison signals
- ATR-based stops
- Shorts
- Deterministic timing
- Backtest-optimized heuristics

---

## Relationship to Execution V1

Execution V2 is a clean replacement for Execution V1.
Execution V1 logic is not reused or extended.
Both systems may coexist during transition.

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

- Prior daily swing high (pivot level)
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

- Position size is determined via a volatility proxy
- No ATR-based stops or fixed R-multiples are used
- A hard account-level cap is enforced

Sizing is evaluated only at entry.

---

## Risk Management (Behavioral)

Execution V2 does not use static price stops.

Instead, positions move through a behavioral state machine:

- OPEN: normal behavior
- CAUTION: invalidation signals accumulating
- EXITING: exit in progress

Invalidation is triggered by repeated failure to hold expected structure.
Single-bar violations are insufficient on their own.

---

## Partial Exits (Conditional Trims)

Trims are:
- conditional
- stateful
- non-automatic

Characteristics:
- Only evaluated if price reaches defined structural extension zones
- Only allowed once per level
- Never forced

Trims do not imply trade failure.

---

## Full Exit Logic

A full exit occurs only when:
- behavioral invalidation threshold is reached
- or global regime forces reduction

No fixed price or volatility stop can trigger a full exit.

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
- Fixed price stops
- Shorts
- Deterministic timing
- Backtest-optimized heuristics

---

## Relationship to Execution V1

Execution V2 is a clean replacement for Execution V1.
Execution V1 logic is not reused or extended.
Both systems may coexist during transition.

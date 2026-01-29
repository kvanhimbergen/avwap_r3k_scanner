# Execution V2 Entry Quality Controls

This note describes two **opt-in** entry-quality protections in Execution V2 that improve timing precision **without** increasing churn. Both features are **feature-flagged OFF by default** and deterministic/offline-first.

## 1) Edge Window (sub-minute re-checks)

**Goal:** Confirm a near-trigger entry without increasing the main poll loop speed.

**How it works**
- During a single `run_once` cycle, if a candidate is *near* its pivot level but not yet confirmed, the engine can perform a small, **bounded** number of deterministic re-checks.
- Re-checks are spaced by a **fixed** delay and stop immediately once a BOH confirmation occurs.
- Re-checks only run when the feature flag is enabled.

**Key traits**
- Deterministic and bounded (fixed count, fixed delay).
- No changes to systemd or poll interval.
- No repeated intent creation for the same symbol within a cycle.

## 2) One-shot per symbol per session (anti-churn)

**Goal:** Prevent multiple entry fills for the same symbol in the same NY trading session unless a deterministic reset condition occurs.

**How it works**
- When a **buy** entry is filled (paper sim or Alpaca paper fills), a per-(date_ny, strategy_id, symbol) marker is stored in the SQLite `StateStore`.
- Subsequent entry attempts for that symbol on the same NY date are blocked unless the configured reset mode allows it.
- The initial reset mode is **cooldown** (deterministic time-based reset).

## Feature flags (defaults are OFF)

- `EDGE_WINDOW_ENABLED` (default: `0`)
- `EDGE_WINDOW_RECHECKS` (default: `3`)
- `EDGE_WINDOW_RECHECK_DELAY_SEC` (default: `5`)
- `EDGE_WINDOW_PROXIMITY_PCT` (default: `0.002`)
- `ONE_SHOT_PER_SYMBOL_ENABLED` (default: `0`)
- `ONE_SHOT_RESET_MODE` (default: `cooldown`)
- `ONE_SHOT_COOLDOWN_MINUTES` (default: `120`)

## Verification / Observability

- `state/portfolio_decision_latest.json`
  - `intents_meta.edge_window` → shows whether the edge window was enabled and any rechecks/confirmations.
  - `intents_meta.one_shot` → shows one-shot configuration used for the cycle.
  - `actions.skipped` → includes one-shot skip reasons (e.g., `one_shot_cooldown_active`).
- Execution ledgers (`ledger/PAPER_SIM/` or `ledger/ALPACA_PAPER/`) record fills; the **one-shot marker** persists in `data/execution_v2.sqlite`.

## Roadmap note

A more advanced “structure reset v2” (e.g., pivot/anchor change) remains future work; for now resets are deterministic cooldown-based.

# Backtest Invalidation Checklist

A backtest is **invalid** if any of the following occur:

## Provenance or identity drift

- **git SHA drift** (code changed)
- **config drift** (config hash changed)
- **data drift** (data hash changed)
- **data path drift** (running against different input files)
- **execution mode drift** (single vs sweep vs walk-forward)
- **parameters drift** (entry model, slippage, risk controls, etc.)

## Integrity and parity failures

- **Parity failure** between `scan_engine` and `backtest_engine` outputs
- **Schema drift** (candidate or summary schema mismatch)
- **Missing or inconsistent provenance fields**

## Guardrail and policy violations

- **Guardrail violations** (risk per trade, gross exposure, max positions, entries per day, symbols per day)
- **Kill switch bypass** or unsupported behavior

## Model and execution invalidations

- **Fill model changes** (entry/exit logic or fill assumptions changed)
- **Determinism violations** (non-repeatable outcomes on identical inputs)

---

## If you see a result without X, it is invalid.

A result is invalid if it does **not** include all required provenance fields in `summary.json` and `run_meta.json`, including:

- `run_id`
- `git_sha`
- `config_hash`
- `data_hash`
- `data_path`
- `execution_mode`
- `parameters_used`

If any of these are missing or empty, treat the result as invalid and do **not** use it for decisions.

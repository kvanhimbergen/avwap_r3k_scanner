# S2_LETF_ORB_AGGRO

Aggressive layered strategy for Execution V2 candidate generation.

## Goal
- Add an aggressive leveraged-ETF sleeve without changing AVWAP core logic.
- Keep full auditability for paper-trading parameter tuning.

## Universe Profiles
- `aggressive_expanded` (default):
  - Leveraged ETFs plus liquid high-beta ETFs/equities (e.g., `SPY`, `QQQ`, `IWM`, `NVDA`, `TSLA`, `MSTR`, `COIN`, `PLTR`).
- `leveraged_only`:
  - Restricts generation to the leveraged ETF basket only.
- Select with:
  - `--universe-profile aggressive_expanded`
  - `--universe-profile leveraged_only`

## Producer
- Module: `strategies/s2_letf_orb_aggro.py`
- Output candidate CSV defaults to:
  - `state/strategies/SCHWAB_401K_MANUAL/S2_LETF_ORB_AGGRO/daily_candidates_layered_<YYYY-MM-DD>.csv`
- Signal/audit ledger defaults to:
  - `ledger/STRATEGY_SIGNALS/S2_LETF_ORB_AGGRO/<YYYY-MM-DD>.jsonl`

## Candidate Schema
The producer emits rows compatible with `execution_v2.buy_loop` and includes:
- Required execution columns:
  - `Symbol`, `Direction`, `Entry_Level`, `Stop_Loss`, `Target_R1`, `Target_R2`, `Entry_DistPct`, `Price`
- Strategy routing:
  - `Strategy_ID=S2_LETF_ORB_AGGRO`
- Audit columns:
  - `Setup`, `Anchor`, `Bucket`, `Score`, `Ret20`, `Ret63`, `ATR14Pct`, `ADV20`

## Signal Model
- Hard risk/quality gates:
  - `price_ok`, `liquidity_ok`
- Signal gates:
  - `trend_ok`, `momentum_ok`, `breakout_ok`
- Eligibility:
  - all hard gates must pass
  - at least `min_signal_gates` signal gates must pass (default `2`)
- Tune from CLI:
  - `--min-signal-gates 1` (more aggressive)
  - `--min-signal-gates 2` (default balance)
  - `--min-signal-gates 3` (strict confluence)

## Layering Behavior
- By default, the producer merges with `daily_candidates.csv`.
- Symbol conflicts are fail-safe:
  - Existing base-candidate symbol is preserved.
  - Strategy candidate is dropped.
  - Reason code `symbol_conflict_with_base_candidates` is written to signal ledger.

## Buy Loop Integration
- `execution_v2.buy_loop` now honors optional `Strategy_ID` per candidate row.
- If `Strategy_ID` is missing/blank, it defaults to `S1_AVWAP_CORE`.
- AVWAP behavior is unchanged for existing candidate files without `Strategy_ID`.

## Sleeve Limits
- `config/s2_sleeves.json` includes:
  - `S2_LETF_ORB_AGGRO.max_concurrent_positions=3`
  - `S2_LETF_ORB_AGGRO.max_gross_exposure_usd=2500`
  - `S2_LETF_ORB_AGGRO.max_daily_loss_usd=150`

## Example
```bash
python -m strategies.s2_letf_orb_aggro \
  --asof 2026-02-10 \
  --universe-profile aggressive_expanded \
  --base-candidates-csv daily_candidates.csv
```

Then run execution using the layered file:
```bash
python -m execution_v2.execution_main \
  --candidates-csv state/strategies/SCHWAB_401K_MANUAL/S2_LETF_ORB_AGGRO/daily_candidates_layered_2026-02-10.csv \
  --run-once
```

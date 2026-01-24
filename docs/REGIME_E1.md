# Phase E1 — Regime Detection (Measurement Only)

## Purpose
Phase E1 adds **measurement-only** regime detection that is **offline, deterministic, and append-only**. It produces descriptive regime labels for analytics/backtests without modifying execution, portfolio decisions, or live trading gates.

## Constraints
- **Measurement-only:** outputs are recorded for analytics only.
- **Offline only:** inputs are local caches/fixtures; no network calls.
- **Deterministic:** same inputs yield identical outputs and `regime_id` hashes.
- **Append-only:** regime records are JSONL ledger entries.
- **Fail-closed:** missing inputs emit deterministic `REGIME_E1_SKIPPED` records.
- **No ML/adaptation:** fixed thresholds only.

## Inputs (Offline)
The classifier uses `cache/ohlcv_history.parquet` (or a specified local path) with at least:
- `Date` (or `date`)
- `Ticker`/`Symbol`
- `Close`

Symbols used:
- `SPY` for volatility, drawdown, and trend.
- `IWM` for breadth fallback (ratio vs `SPY`) when a broad symbol universe is unavailable.

## Feature Definitions (Deterministic)
All features are computed using data **on or before** `ny_date`.

### Volatility
- **Definition:** annualized realized volatility of SPY daily returns.
- **Lookback:** 20 trading days.

### Drawdown
- **Definition:** minimum peak-to-trough drawdown over SPY closes.
- **Lookback:** 63 trading days.

### Trend
- **Definition:** SPY MA crossover strength (`MA50 / MA200 - 1`).
- **Lookbacks:** 50d short, 200d long.

### Breadth
Two deterministic methods:
1. **Above-MA fraction (preferred):** fraction of symbols with close >= 50d MA using at least 20 symbols.
2. **Ratio fallback:** `IWM / SPY` ratio vs its 50d MA (breadth = 1.0 if ratio >= MA else 0.0).

## Classification Rules
Thresholds (fixed):
- Volatility: `VOL_HIGH=0.30`, `VOL_MODERATE=0.20`
- Drawdown: `DRAWDOWN_STRESSED=-0.20`, `DRAWDOWN_RISK_OFF=-0.10`
- Trend: `TREND_DOWN=-0.02`, `TREND_UP=0.02`
- Breadth: `BREADTH_STRONG=0.55`, `BREADTH_WEAK=0.45`

Rule table:
- **STRESSED**: high vol + deep drawdown or high vol + downtrend (or deep drawdown alone).
- **RISK_OFF**: moderate/high vol OR drawdown <= -10% OR trend negative OR weak breadth.
- **RISK_ON**: low/moderate vol AND shallow drawdown AND positive trend AND strong breadth.
- **NEUTRAL**: otherwise.

Confidence is deterministic, based on the number of rule conditions satisfied.

## Ledger Records (Append-Only)
Records are written to:
```
ledger/REGIME_E1/{ny_date}.jsonl
```

Two record types:
- `REGIME_E1_SIGNAL` (successful classification)
- `REGIME_E1_SKIPPED` (missing inputs)

Each record includes:
- `record_type`
- `schema_version`
- `ny_date`
- `as_of_utc`
- `regime_id` (sha256 of canonical JSON payload)
- `regime_label`, `confidence`, `signals`, `inputs_snapshot`, `reason_codes`
- `provenance`

### Example (signal)
```json
{"as_of_utc":"2024-12-31T16:00:00+00:00","confidence":0.8,"inputs_snapshot":{"breadth":{"method":"iwm_spy_ratio"},"drawdown_closes":[...],"last_date":"2024-12-31","ny_date":"2024-12-31","spy_close":123.45,"trend_ma_long":120.1,"trend_ma_short":122.3,"vol_returns":[...]},"ny_date":"2024-12-31","provenance":{"module":"analytics.regime_e1_runner"},"reason_codes":["vol_calm","drawdown_shallow","trend_positive","breadth_strong"],"record_type":"REGIME_E1_SIGNAL","regime_id":"...","regime_label":"RISK_ON","schema_version":1,"signals":{"breadth":{"lookback":50,"method":"iwm_spy_ratio","value":1.0},"drawdown":{"lookback":63,"value":-0.02},"trend":{"lookback_long":200,"lookback_short":50,"ma_long":120.1,"ma_short":122.3,"value":0.018},"volatility":{"lookback":20,"value":0.12}}}
```

### Example (skipped)
```json
{"as_of_utc":"2024-12-31T16:00:00+00:00","inputs_snapshot":{"history_path":"cache/ohlcv_history.parquet","ny_date":"2024-12-31"},"ny_date":"2024-12-31","provenance":{"module":"analytics.regime_e1_runner"},"reason_codes":["missing_history_path"],"record_type":"REGIME_E1_SKIPPED","regime_id":"...","schema_version":1}
```

## How to Run
Single day:
```bash
python -m analytics.regime_e1_runner --ny-date 2024-12-31 --as-of-utc 2024-12-31T16:00:00+00:00
```

Historical range:
```bash
python -m analytics.regime_e1_historical --start 2024-01-01 --end 2024-12-31
```

## Interpreting Regime Labels
- **RISK_ON:** calm volatility, shallow drawdown, positive trend, strong breadth.
- **NEUTRAL:** mixed signals without clear dominance.
- **RISK_OFF:** elevated volatility, negative trend, or meaningful drawdown.
- **STRESSED:** high volatility paired with deep drawdown or downtrend.

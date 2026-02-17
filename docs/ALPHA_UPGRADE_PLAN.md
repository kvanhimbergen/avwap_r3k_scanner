# Professional-Grade Alpha-Maximizing Upgrade Plan

## Context

The AVWAP R3K Scanner is a production-grade automated trading system scanning the Russell 3000 daily for short-term candidates using Anchored VWAP technical analysis, executing via Alpaca. The system is reliable, deterministic, and auditable — but uses absolute thresholds for signal selection, ignores inter-position correlation, has a coarse regime model (SPY vs 200 SMA), and backtests suffer from survivorship bias. This plan upgrades 7 areas in dependency order, where each phase ships independently and builds on prior work.

## Dependency Graph

```
Phase 1 (Slippage)           [no deps]
    |
Phase 2 (Feature Store)      [benefits from Phase 1]
    |
    +---> Phase 3 (Cross-Sectional Scoring)  [needs Feature Store]
    |
    +---> Phase 4 (Multi-Factor Regime)      [needs Feature Store]
    |         |
    |         v
    |     Phase 5 (Correlation Sizing)       [needs Regime + Feature Store]
    |         |
    |         v
    |     Phase 6 (Dynamic Exposure)         [needs Regime + Correlation + Slippage]
    |
    +---> Phase 7 (Survivorship)             [needs Feature Store]
```

---

## Phase 1: Slippage Measurement + Execution Timing Analysis

**Scope: Medium** | **Status: DONE**

**Objective:** Log expected vs actual fill prices, build slippage model by liquidity bucket, analyze entry timing by time-of-day. You cannot optimize what you do not measure — this calibrates `BACKTEST_SLIPPAGE_BPS` (currently fixed 2.5) and reveals whether BOH confirmation is net-positive.

### Tasks

- [x] Create `analytics/slippage_model.py` — SlippageEvent dataclass, liquidity bucket classification (mega/large/mid/small by ADV), aggregation functions
- [x] Create `analytics/slippage_timing.py` — Time-of-day bucketing (30-min windows 09:30-16:00), entry quality by window
- [x] Modify `execution_v2/execution_main.py` — After fill confirmation, emit `EXECUTION_SLIPPAGE` record to ledger via `_maybe_log_slippage()` (gated, fail-open)
- [x] Modify `backtest_engine.py` — Add `ideal_fill_price` and `slippage_actual_bps` columns to trades DataFrame
- [x] Modify `config.py` — Add `SLIPPAGE_LIQUIDITY_BUCKETS`, `SLIPPAGE_LEDGER_ENABLED`
- [x] Create `tests/test_slippage_model.py` — Unit tests for slippage calculations, liquidity bucket assignment, edge cases
- [x] Create `tests/test_slippage_timing.py` — Unit tests for timing bucketing

### Slippage Event Schema

```python
@dataclass(frozen=True)
class SlippageEvent:
    schema_version: int = 1
    record_type: str = "EXECUTION_SLIPPAGE"
    date_ny: str
    symbol: str
    strategy_id: str
    expected_price: float      # AVWAP-derived entry level
    ideal_fill_price: float    # market open or limit price
    actual_fill_price: float   # Alpaca fill
    slippage_bps: float        # (actual - ideal) / ideal * 10000
    adv_shares_20d: float
    liquidity_bucket: str      # mega(>=5M) / large(>=2M) / mid(>=750K)
    fill_ts_utc: str
    time_of_day_bucket: str    # "09:30-10:00", etc.
```

### Liquidity Buckets (based on existing ADV_MIN_SHARES = 750K floor)

| Bucket | ADV Threshold |
|--------|---------------|
| mega   | >= 5M shares  |
| large  | >= 2M shares  |
| mid    | >= 750K shares |
| small  | < 750K (shouldn't appear given filters) |

### Persistence

New ledger directory `ledger/EXECUTION_SLIPPAGE/{date}.jsonl` — same append-only JSONL pattern as existing ledger dirs.

### Verification

- [x] Backtest trades CSV contains `ideal_fill_price` and `slippage_actual_bps` columns
- [x] Live execution writes `EXECUTION_SLIPPAGE` records
- [x] Aggregation by liquidity bucket and time-of-day produces meaningful output
- [x] Existing test suite passes unchanged (observational only, no behavioral change)

---

## Phase 2: Feature Store + Walk-Forward Validation

**Scope: Large** | **Status: DONE**

**Objective:** Centralize all computed features in a versioned, point-in-time-correct Parquet store. Extend `backtest_sweep.py` with Combinatorial Purged Cross-Validation (CPCV) and Deflated Sharpe Ratio (DSR) to combat overfitting.

### Tasks

- [x] Create `feature_store/__init__.py`
- [x] Create `feature_store/store.py` — Core store: Parquet partitioned by date, versioned schemas, point-in-time reads
- [x] Create `feature_store/schemas.py` — Frozen dataclass schemas per feature type (trend, regime, avwap_state)
- [x] Create `feature_store/writers.py` — Atomic writes (reuse `cache_store.py` tmp+rename pattern)
- [x] Create `feature_store/readers.py` — `get_features(symbol, date)` with strict "no future data" enforcement
- [x] Create `feature_store/versioning.py` — Schema version tracking, migration helpers
- [x] Create `analytics/cpcv.py` — Combinatorial Purged Cross-Validation (Lopez de Prado framework)
- [x] Create `analytics/deflated_sharpe.py` — DSR computation
- [x] Modify `scan_engine.py` — After computing candidates, persist features to store (behind `FEATURE_STORE_WRITE_ENABLED` flag)
- [x] Modify `backtest_sweep.py` — Add `validation_mode` param: `"rolling"` (existing), `"cpcv"` (new). Add DSR to `build_summary_row()`
- [x] Modify `backtest_engine.py` — Optionally read from feature store (behind `BACKTEST_USE_FEATURE_STORE` flag)
- [x] Modify `config.py` — Add `FEATURE_STORE_DIR`, `FEATURE_STORE_WRITE_ENABLED`, `FEATURE_STORE_SCHEMA_VERSION`, `BACKTEST_VALIDATION_MODE`, `BACKTEST_CPCV_N_GROUPS`, `BACKTEST_CPCV_K_SPLITS`, `BACKTEST_PURGE_DAYS`, `BACKTEST_EMBARGO_DAYS`
- [x] Create `tests/test_feature_store.py` — CRUD and point-in-time correctness
- [x] Create `tests/test_cpcv.py` — Split generation and purge/embargo validation
- [x] Create `tests/test_deflated_sharpe.py` — DSR computation against known values

### Feature Store Layout

```
feature_store/v1/{YYYY-MM-DD}/
    trend_features.parquet      # symbol, trend_score, sma50_slope, adx, vol_ratio
    regime_features.parquet     # spy_vol, spy_dd, spy_trend, breadth
    avwap_features.parquet      # symbol, anchor, avwap_slope, dist_pct, setup_state
    _meta.json                  # run_id, git_sha, schema_version (provenance)
```

Each date partition is written atomically. Point-in-time reads enforce `date <= requested_date` and return the latest available snapshot — never future data.

### CPCV Implementation

Given N groups of trading days and choosing K test groups at a time, generate all C(N,K) combinations. For each combination, apply a purge window (default 5 days) and embargo window (default 3 days) to prevent leakage from serial correlation. Returns same split format as existing `compute_walk_forward_splits()` so the sweep loop works unchanged.

### Deflated Sharpe Ratio

```python
def deflated_sharpe(
    observed_sharpe: float,
    n_trials: int,         # number of parameter combos tried
    variance_sharpe: float, # variance of Sharpe across trials
    T: int,                 # number of return observations
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """p-value that observed Sharpe > 0 given multiple testing."""
```

### Verification

- [x] Feature store populated during scan runs
- [x] Backtests with `BACKTEST_USE_FEATURE_STORE=True` produce identical results to inline computation (parity test)
- [x] CPCV produces more conservative Sharpe estimates than rolling walk-forward
- [x] `deflated_sharpe` column appears in summary tables
- [x] Point-in-time correctness: features for date D3 never returned when reading as-of D2

---

## Phase 3: Cross-Sectional Scoring

**Scope: Medium** | **Status: DONE**

**Objective:** Replace absolute thresholds (`TREND_SCORE_MIN_LONG: 5.0`) with universe-relative rankings. "Top-decile today" replaces "above 5.0". Absolute thresholds remain as hard safety floors.

### Tasks

- [x] Create `analytics/cross_sectional.py` — Z-score and percentile rank computation for configurable feature set (trend_score, dist_pct, AVWAP_slope, ATR_pct). Composite rank formula.
- [x] Modify `scan_engine.py` — After `build_candidate_row()` produces all raw candidates, compute cross-sectional ranks. Add columns: `TrendScore_Zscore`, `TrendScore_Pctile`, `DistPct_Zscore`, `Composite_Rank`. Primary selection becomes `Composite_Rank <= top_decile_cutoff`. Bump `SchemaVersion` to 2.
- [x] Modify `backtest_engine.py` — Pipe day's candidate universe through cross-sectional ranking before entry selection (`_scan_as_of()` already produces all candidates for a date)
- [x] Modify `config.py` — Add `CROSS_SECTIONAL_ENABLED`, `CROSS_SECTIONAL_TOP_DECILE`, `CROSS_SECTIONAL_FEATURES`, `CROSS_SECTIONAL_HARD_FLOOR_TREND_SCORE`
- [x] Modify `feature_store/writers.py` — Store daily cross-sectional distributions (mean, std, percentiles)
- [x] Create `tests/test_cross_sectional.py`

### Composite Rank Formula

```python
def composite_rank(trend_score_z, dist_pct_z, avwap_slope_z, weights=None):
    w = weights or {"trend": 0.4, "dist": 0.3, "slope": 0.3}
    return w["trend"] * trend_score_z - w["dist"] * dist_pct_z + w["slope"] * avwap_slope_z
    # dist_pct inverted: closer to AVWAP = better
```

### Integration Point

Current flow: build rows -> append -> return DataFrame.
New flow: build rows -> compute z-scores across day's candidates -> filter to top decile -> return enriched DataFrame. Hard floors still apply (no candidates below `TREND_SCORE_MIN_LONG` regardless of z-score).

### Schema Versioning

`CANDIDATE_COLUMNS` list in `scan_engine.py` (~line 46) extended with new columns. `SchemaVersion` bumps to 2. Backtest engine's `_validate_candidates()` handles both v1 and v2.

### Verification

- [x] Candidate CSV includes z-score and percentile columns
- [x] Cross-sectional distributions stored in feature store per day
- [x] Hard floor safety gates still apply
- [x] Backward compatible: SchemaVersion=1 backtests still work
- [x] Edge cases handled: single candidate (fall back to absolute), all identical values, NaN

---

## Phase 4: Multi-Factor Regime Model

**Scope: Large** | **Status: TODO**

**Objective:** Replace the current E1 classifier (hard thresholds on SPY vol/drawdown/trend/breadth producing discrete RISK_ON/NEUTRAL/RISK_OFF) with a multi-factor model including credit spread proxy (HYG/LQD ratio), VIX term structure, and regime transition smoothing to prevent whipsaw.

### Tasks

- [ ] Create `analytics/regime_e2_features.py` — Extended feature set: all E1 features + credit_spread (HYG-LQD ratio z-score), vix_term_structure (VIX-VIX3M), cross-asset momentum (GLD, TLT RS)
- [ ] Create `analytics/regime_e2_classifier.py` — Continuous regime score (0.0-1.0) instead of discrete labels, multi-factor weighting
- [ ] Create `analytics/regime_transition.py` — Transition smoothing: require N consecutive days of new regime before flipping (prevents single-day whipsaw)
- [ ] Modify `analytics/regime_e1_features.py` — Add credit and VIX features to `RegimeFeatureSet` (backward compatible with defaults)
- [ ] Modify `portfolio/risk_controls.py` — `_regime_to_throttle()` accepts continuous regime score; interpolates instead of discrete {1.0, 0.6, 0.2} mapping
- [ ] Modify `config.py` — Add `REGIME_MODEL_VERSION` (`"e1"` | `"e2"`), `REGIME_TRANSITION_SMOOTHING_DAYS`, `REGIME_CREDIT_SPREAD_LOOKBACK`
- [ ] Modify `scan_engine.py` — Ensure `BENCHMARK_TICKERS` (HYG, LQD, GLD, TLT) are always backfilled in history cache
- [ ] Modify `feature_store/writers.py` — Persist regime E2 features
- [ ] Create `tests/test_regime_e2_features.py`
- [ ] Create `tests/test_regime_e2_classifier.py`
- [ ] Create `tests/test_regime_transition.py`

### Regime Transition Smoothing

```python
class RegimeTransitionDetector:
    def __init__(self, smoothing_days: int = 5):
        self._history: list[dict] = []

    def update(self, raw_regime: str, confidence: float, date: str) -> str:
        self._history.append({"regime": raw_regime, "confidence": confidence, "date": date})
        if len(self._history) < self.smoothing_days:
            return raw_regime
        recent = self._history[-self.smoothing_days:]
        if all(r["regime"] == raw_regime for r in recent):
            return raw_regime
        return self._history[-self.smoothing_days - 1]["regime"]  # sticky
```

### Credit Spread Proxy

```python
hyg_lqd_ratio = hyg_close / lqd_close  # falling = widening spreads = risk off
credit_z = (ratio - rolling_mean) / rolling_std
```

HYG and LQD are already in `BENCHMARK_TICKERS`.

### Backward Compatibility

E1 remains default. `REGIME_MODEL_VERSION=e2` activates new model. Both write to their respective ledger dirs. `risk_controls.py` reads from whichever is configured.

### Verification

- [ ] E2 produces fewer regime transitions than E1 on same data
- [ ] Risk controls smoothly interpolate between regimes
- [ ] All E1 tests pass (E1 is default)
- [ ] Fail-open: missing HYG/LQD data degrades gracefully to E1 behavior
- [ ] Backtest with E2 shows reduced portfolio volatility during regime transitions

---

## Phase 5: Correlation-Aware Sizing

**Scope: Medium** | **Status: TODO**

**Objective:** Measure pairwise correlation within the open book, penalize concentrated correlated exposure, enforce sector caps. Five highly correlated tech stocks is functionally one concentrated bet.

### Tasks

- [ ] Create `analytics/correlation_matrix.py` — Rolling pairwise correlation computation (60-day default), sector-level aggregation
- [ ] Create `execution_v2/correlation_sizing.py` — Correlation penalty function, sector cap enforcement
- [ ] Modify `execution_v2/sizing.py` — `compute_size_shares()` gains `correlation_penalty` param. Formula becomes: `dollar_alloc = equity * base_risk_pct * risk_scale * (1 - correlation_penalty)`
- [ ] Modify `execution_v2/buy_loop.py` — Before sizing, compute correlation of candidate with open positions, pass penalty
- [ ] Modify `backtest_engine.py` — Same logic in entry fill path (~line 562-614)
- [ ] Modify `config.py` — Add `CORRELATION_AWARE_SIZING_ENABLED`, `CORRELATION_LOOKBACK_DAYS`, `CORRELATION_PENALTY_THRESHOLD` (0.6 default), `MAX_SECTOR_EXPOSURE_PCT` (0.3 default), `MAX_CORRELATED_CLUSTER_EXPOSURE_PCT`
- [ ] Modify `analytics/risk_attribution.py` — Add `correlation_penalty` to attribution events
- [ ] Modify `feature_store/writers.py` — Store daily correlation matrices (candidates + open positions only)
- [ ] Create `tests/test_correlation_matrix.py`
- [ ] Create `tests/test_correlation_sizing.py`

### Correlation Penalty

```python
def correlation_penalty(candidate, open_positions, corr_matrix, threshold=0.6, max_penalty=0.5):
    """Returns penalty in [0, max_penalty]. Higher correlation => smaller size."""
    if not open_positions or candidate not in corr_matrix.index:
        return 0.0
    corrs = [abs(corr_matrix.loc[candidate, pos]) for pos in open_positions if pos in corr_matrix.columns]
    if not corrs:
        return 0.0
    avg_corr = sum(corrs) / len(corrs)
    if avg_corr <= threshold:
        return 0.0
    excess = (avg_corr - threshold) / (1.0 - threshold)
    return min(excess * max_penalty, max_penalty)
```

### Sector Caps

Enforce `MAX_SECTOR_EXPOSURE_PCT` (e.g., 30%) at portfolio level. If existing Tech positions = 28% and new Tech candidate would push to 35%, BLOCK the entry (logged in portfolio decisions).

### Verification

- [ ] Sizing reduced for candidates correlated with existing positions
- [ ] Sector caps enforced (BLOCK reason in portfolio decisions)
- [ ] Correlation matrices persisted in feature store
- [ ] Risk attribution events include correlation penalty
- [ ] Feature flag off = identical to pre-Phase-5 behavior

---

## Phase 6: Dynamic Gross Exposure

**Scope: Medium** | **Status: TODO**

**Objective:** Scale portfolio gross exposure inversely with realized portfolio volatility. Low vol + RISK_ON = higher exposure. Vol spike + regime deterioration = lower exposure.

### Tasks

- [ ] Create `portfolio/dynamic_exposure.py` — Gross exposure target computation, vol-targeting, regime-adaptive scaling
- [ ] Modify `portfolio/risk_controls.py` — `build_risk_controls()` incorporates dynamic exposure target; `max_gross_exposure` becomes a function of realized portfolio vol
- [ ] Modify `execution_v2/buy_loop.py` — Query dynamic exposure module before sizing
- [ ] Modify `backtest_engine.py` — `max_gross_exposure_pct` (~line 416) becomes dynamic per day
- [ ] Modify `config.py` — Add `DYNAMIC_EXPOSURE_ENABLED`, `TARGET_PORTFOLIO_VOL` (e.g., 0.15), `MAX_GROSS_EXPOSURE_CEILING`, `MIN_GROSS_EXPOSURE_FLOOR`, `PORTFOLIO_VOL_LOOKBACK_DAYS`
- [ ] Modify `analytics/risk_attribution.py` — Track `target_exposure`, `actual_exposure`, `portfolio_vol`
- [ ] Create `tests/test_dynamic_exposure.py`

### Vol-Targeting Formula

```python
def compute_target_exposure(
    realized_portfolio_vol: float,  # annualized
    target_vol: float,              # e.g., 0.15
    regime_multiplier: float,       # from Phase 4, 0.0-1.0
    floor: float = 0.2,
    ceiling: float = 1.0,
) -> float:
    if realized_portfolio_vol <= 0:
        return ceiling * regime_multiplier
    raw_target = target_vol / realized_portfolio_vol
    regime_adjusted = raw_target * regime_multiplier
    return max(floor, min(ceiling, regime_adjusted))
```

### Integration

The dynamic exposure target replaces the static `base_max_gross_exposure` in `build_risk_controls()`. The drawdown guardrail (~line 373-382) still applies as an independent kill switch.

### Verification

- [ ] Gross exposure varies over time in backtest equity curve
- [ ] Attribution events include portfolio vol and target exposure
- [ ] Max drawdown improves vs Phase 5 backtest
- [ ] Floor/ceiling caps never violated
- [ ] Feature flag off = identical to pre-Phase-6 behavior

---

## Phase 7: Survivorship-Clean Backtesting

**Scope: Large** | **Status: TODO**

**Objective:** Source historical R3K constituency lists, verify corporate actions, use point-in-time earnings dates. Eliminates survivorship bias that silently inflates backtest returns.

### Tasks

- [ ] Create `universe/historical_constituency.py` — Load/query historical R3K membership by date. Format: `universe/historical/{YYYY-MM-DD}.csv` (bi-weekly snapshots, interpolated)
- [ ] Create `universe/corporate_actions.py` — Detect splits, mergers, delistings. Adjust OHLCV prices retroactively
- [ ] Create `universe/point_in_time_earnings.py` — Historical earnings dates for backtest-mode earnings exclusion (replaces live yfinance lookup which has lookahead bias)
- [ ] Modify `universe.py` — Add `load_universe_as_of(date)` that returns R3K membership as of a specific historical date
- [ ] Modify `backtest_engine.py` — Universe loading (~line 491-503) switches to `load_universe_as_of(session_date)` when `BACKTEST_USE_DATED_UNIVERSE_SNAPSHOTS=True` (config flag already exists but is unused)
- [ ] Modify `scan_engine.py` — `is_near_earnings_cached()` (~line 402) uses point-in-time earnings dates in backtest mode
- [ ] Modify `cache_store.py` — `upsert_history()` applies split adjustments before persisting
- [ ] Modify `config.py` — Add `BACKTEST_HISTORICAL_CONSTITUENCY_PATH`, `BACKTEST_CORPORATE_ACTIONS_PATH`, `BACKTEST_POINT_IN_TIME_EARNINGS_PATH`, `BACKTEST_APPLY_SPLIT_ADJUSTMENTS`
- [ ] Create `tests/test_historical_constituency.py`
- [ ] Create `tests/test_corporate_actions.py`
- [ ] Create `tests/test_point_in_time_earnings.py`

### Corporate Action Handling

```python
@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    action_type: str  # "split", "merger", "delisting"
    effective_date: str
    ratio: float | None  # 2.0 = 2-for-1 split
    acquirer: str | None = None
```

OHLCV cache adjusted retroactively for splits (divide pre-split prices by ratio). Delistings trigger force-exit at last available price in backtest.

### Data Sourcing Options

- Historical constituency: (a) manual bi-weekly CSV snapshots of IWV holdings, (b) Sharadar/Quandl, (c) Internet Archive
- Point-in-time earnings: yfinance historical + SEC EDGAR filings
- Corporate actions: yfinance `.actions` + `.splits` + manual CSV for edge cases

### Verification

- [ ] Backtest with historical constituency produces different (typically worse) results than survivorship-biased universe
- [ ] Corporate actions correctly applied in OHLCV cache
- [ ] Point-in-time earnings exclusion works in backtest mode
- [ ] `BACKTEST_USE_DATED_UNIVERSE_SNAPSHOTS` flag works as documented
- [ ] Indicators remain smooth across split adjustment dates
- [ ] Provenance includes `constituency_source` and `corporate_actions_hash`

---

## Design Invariants (All Phases)

- **Feature-flagged**: Every phase is gated behind a config flag, default OFF
- **Append-only ledgers**: New event types get new ledger subdirs, never mutate existing
- **Deterministic provenance**: All new artifacts include run_id, git_sha, schema_version
- **Fail-open**: Missing data degrades gracefully (warnings, not crashes)
- **Backward compatible**: Existing SchemaVersion=1 candidates and E1 regime work unchanged
- **Tested**: Every new module has a corresponding test file; parity tests ensure no behavioral regression when flags are off

## Scope Summary

| Phase | What | Scope | Key Files Modified |
|-------|------|-------|--------------------|
| 1 | Slippage Measurement | M | buy_loop.py, backtest_engine.py, config.py |
| 2 | Feature Store + CPCV | L | scan_engine.py, backtest_sweep.py, backtest_engine.py, config.py |
| 3 | Cross-Sectional Scoring | M | scan_engine.py, backtest_engine.py, config.py |
| 4 | Multi-Factor Regime | L | regime_e1_features.py, risk_controls.py, config.py |
| 5 | Correlation Sizing | M | sizing.py, buy_loop.py, backtest_engine.py, config.py |
| 6 | Dynamic Exposure | M | risk_controls.py, buy_loop.py, backtest_engine.py, config.py |
| 7 | Survivorship Backtesting | L | universe.py, backtest_engine.py, cache_store.py, config.py |

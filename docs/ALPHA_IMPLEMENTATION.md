# Alpha Upgrade Implementation Guide

Copy-paste prompts for Claude Code. Each session is a fresh conversation.
Start each session from the project root: `cd ~/avwap_r3k_scanner`

**Rules:**
- One session = one focused scope (marked by `---` dividers below)
- After each session, commit before starting the next
- Large phases are split into multiple sessions
- Each prompt is self-contained — no prior conversation needed

---

## Phase 1: Slippage Measurement + Execution Timing Analysis

### Session 1.1 — Core slippage module + timing module + tests

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 1: Slippage Measurement.

Implement the following tasks from the plan:

1. Create analytics/slippage_model.py:
   - SlippageEvent frozen dataclass exactly as specified in the plan
   - classify_liquidity_bucket(adv_shares_20d) function returning "mega"/"large"/"mid"/"small" per the ADV thresholds in the plan
   - compute_slippage_bps(ideal_fill_price, actual_fill_price) function
   - append_slippage_event() that writes to ledger/EXECUTION_SLIPPAGE/{date_ny}.jsonl following the exact same append-only JSONL pattern used in portfolio/risk_controls.py (read that file for the _append_record pattern)
   - aggregate_slippage_by_bucket(events) and aggregate_slippage_by_time(events) summary functions

2. Create analytics/slippage_timing.py:
   - classify_time_bucket(fill_ts_utc) function that maps fill timestamps to 30-minute windows from "09:30-10:00" through "15:30-16:00"
   - Handle pre-market and after-hours edge cases (bucket as "pre-market" or "after-hours")

3. Create tests/test_slippage_model.py:
   - Test slippage_bps calculation with known values (positive slippage, negative slippage, zero)
   - Test liquidity bucket assignment at boundaries (exactly 5M, exactly 2M, exactly 750K, below 750K)
   - Test NaN and zero price edge cases
   - Test JSONL append creates correct file structure

4. Create tests/test_slippage_timing.py:
   - Test each 30-minute bucket boundary
   - Test pre-market (before 09:30) and after-hours (after 16:00)
   - Test timezone handling (UTC input, ET bucket output)

Follow existing patterns in the codebase:
- Read analytics/ directory for module style conventions
- Read portfolio/risk_controls.py for the JSONL ledger append pattern
- Use dataclasses, not Pydantic, matching existing analytics modules

Run pytest tests/test_slippage_model.py tests/test_slippage_timing.py after implementation.
```

### Session 1.2 — Wire into execution and backtest + config

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 1: Slippage Measurement.

The core slippage modules (analytics/slippage_model.py and analytics/slippage_timing.py) are already implemented. Now wire them into the execution and backtest pipelines:

1. Modify config.py:
   - Add SLIPPAGE_LEDGER_ENABLED: bool = True (default on since it's observational)
   - Add SLIPPAGE_LIQUIDITY_BUCKETS: dict with the ADV thresholds (mega: 5_000_000, large: 2_000_000, mid: 750_000)
   - Follow the existing pattern of how other config flags are defined in this file

2. Modify execution_v2/buy_loop.py:
   - Read the file first to understand the fill confirmation flow
   - After a fill is confirmed (where filled_avg_price is available from Alpaca), call append_slippage_event() with:
     - expected_price = candidate's entry_level (AVWAP-derived)
     - ideal_fill_price = the limit/market price used in the order
     - actual_fill_price = Alpaca's filled_avg_price
     - adv_shares_20d from the candidate row
   - Gate behind cfg.SLIPPAGE_LEDGER_ENABLED
   - Wrap in try/except so slippage logging never breaks the execution loop (fail-open)

3. Modify backtest_engine.py:
   - Read the file to find where trades are appended to the trades list (around line ~549 where bar["Open"] is used as fill price)
   - Add two new columns to each trade dict: "ideal_fill_price" and "slippage_actual_bps"
   - ideal_fill_price = the open price used for entry
   - slippage_actual_bps = the configured BACKTEST_SLIPPAGE_BPS value (so backtest trades record the assumed slippage)
   - These columns are observational — do NOT change any backtest behavior

4. Run the full existing test suite to verify no regressions:
   pytest tests/ -x --timeout=60

Do not add features beyond what's specified. This is observational instrumentation only.
```

### Session 1.3 — Commit Phase 1

```
Read docs/ALPHA_UPGRADE_PLAN.md Phase 1 verification checklist.

Verify all Phase 1 deliverables:
1. Run pytest tests/test_slippage_model.py tests/test_slippage_timing.py -v
2. Confirm analytics/slippage_model.py and analytics/slippage_timing.py exist with the correct interfaces
3. Confirm config.py has SLIPPAGE_LEDGER_ENABLED and SLIPPAGE_LIQUIDITY_BUCKETS
4. Confirm execution_v2/buy_loop.py has the slippage logging call (gated, fail-open)
5. Confirm backtest_engine.py trades include ideal_fill_price and slippage_actual_bps columns
6. Run pytest tests/ -x --timeout=60 to verify no regressions

If everything passes, create a commit with message:
"Add slippage measurement and execution timing analysis (Phase 1)"

Update docs/ALPHA_UPGRADE_PLAN.md: change Phase 1 status from TODO to DONE and check all task checkboxes.
```

---

## Phase 2: Feature Store + Walk-Forward Validation

### Session 2.1 — Feature store core infrastructure

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 2: Feature Store + Walk-Forward Validation.

Build the core feature store infrastructure. This session covers the storage layer only — no integration with scan_engine or backtest yet.

1. Create feature_store/__init__.py (empty, just makes it a package)

2. Create feature_store/schemas.py:
   - Frozen dataclasses for each feature type:
     - TrendFeatures: symbol, trend_score, sma50_slope, adx, vol_ratio, atr_pct
     - RegimeFeatures: spy_vol, spy_drawdown, spy_trend, breadth, regime_label
     - AVWAPFeatures: symbol, anchor, avwap_slope, dist_pct, setup_vwap_control, setup_avwap_control, setup_extension_state, setup_structure_state
   - Each schema has a SCHEMA_VERSION class attribute (int)
   - to_dict() and from_dict() classmethods for serialization

3. Create feature_store/writers.py:
   - Read cache_store.py first to understand the atomic write pattern (tmp file + os.replace)
   - write_feature_partition(date_str, feature_type, df, meta) function:
     - Writes to feature_store/v{version}/{date_str}/{feature_type}.parquet
     - Creates _meta.json sidecar with run_id, git_sha, schema_version (read provenance.py for the provenance pattern)
     - Atomic write: write to .tmp, then os.replace
   - Ensure parent directories are created (os.makedirs with exist_ok=True)

4. Create feature_store/readers.py:
   - read_features(feature_type, as_of_date) -> pd.DataFrame:
     - Finds the latest date partition where date <= as_of_date (CRITICAL: never return future data)
     - Returns the Parquet DataFrame for that date
     - Returns empty DataFrame if no data available
   - read_feature_meta(feature_type, as_of_date) -> dict:
     - Returns the _meta.json contents for the matched partition

5. Create feature_store/versioning.py:
   - get_current_schema_version() -> int
   - get_store_path(version=None) -> Path (defaults to current version)
   - list_available_dates(feature_type) -> list[str]

6. Create feature_store/store.py:
   - FeatureStore class that wraps readers/writers with a configured base directory
   - Constructor takes base_dir (default from config) and schema_version
   - write(date, feature_type, df, meta) delegates to writers
   - read(feature_type, as_of_date) delegates to readers with point-in-time enforcement

7. Create tests/test_feature_store.py:
   - Test write + read roundtrip for each feature type
   - Test point-in-time correctness: write dates D1, D2, D3; read as-of D2; verify D3 is NOT returned
   - Test empty store returns empty DataFrame
   - Test atomic write doesn't leave partial files on error
   - Test _meta.json contains provenance fields
   - Use tmp_path fixture for isolation

Run pytest tests/test_feature_store.py -v after implementation.
```

### Session 2.2 — CPCV and Deflated Sharpe modules

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 2: the CPCV Implementation and Deflated Sharpe Ratio sections.

Build the advanced validation modules. These are standalone analytics — no integration with backtest_sweep yet.

1. Create analytics/cpcv.py:
   - Read backtest_sweep.py first, specifically the compute_walk_forward_splits() function and its return format (list of dicts with "train_dates" and "test_dates" keys)
   - generate_cpcv_splits(trading_days, n_groups, k_test_groups, purge_days=5, embargo_days=3) -> list[dict]:
     - Split trading_days into n_groups roughly equal groups
     - Generate all C(n_groups, k_test_groups) combinations
     - For each combination: test set = selected groups, train set = remaining groups
     - Apply purge: remove purge_days from end of each train segment that borders a test segment
     - Apply embargo: remove embargo_days from start of each test segment
     - Return same format as compute_walk_forward_splits(): list of {"train_dates": [...], "test_dates": [...]}
   - Use itertools.combinations for generating group combos
   - Validate inputs: n_groups >= 2, k_test_groups >= 1, k_test_groups < n_groups

2. Create analytics/deflated_sharpe.py:
   - deflated_sharpe_ratio(observed_sharpe, n_trials, variance_sharpe, T, skew=0.0, kurtosis=3.0) -> float:
     - Implements the Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio
     - Computes the expected maximum Sharpe under the null using E[max] = variance_sharpe * ((1 - euler_gamma) * norm.ppf(1 - 1/n_trials) + euler_gamma * norm.ppf(1 - 1/(n_trials*e)))
     - Adjusts for non-normality: SR_adjusted = SR * sqrt(1 + (skew/6)*SR - ((kurtosis-3)/24)*SR^2)
     - Returns p-value (probability that observed Sharpe > expected max under null)
   - Use scipy.stats.norm for the normal CDF/PPF
   - euler_gamma = 0.5772156649... (Euler-Mascheroni constant)

3. Create tests/test_cpcv.py:
   - Test with 100 trading days, n_groups=5, k_test_groups=2: should produce exactly C(5,2)=10 splits
   - Verify no overlap between train and test dates in any split
   - Verify purge days are removed from train set borders
   - Verify embargo days are removed from test set start
   - Test edge case: n_groups=2, k_test_groups=1 (simple 2-fold)
   - Test that all trading days appear in test sets across all splits

4. Create tests/test_deflated_sharpe.py:
   - Test with known inputs: Sharpe=2.0, n_trials=1, should return low p-value (significant)
   - Test with known inputs: Sharpe=0.5, n_trials=100, should return high p-value (not significant after correction)
   - Test skew and kurtosis adjustments produce different results than defaults
   - Test edge cases: n_trials=1, T=1, zero variance

Run pytest tests/test_cpcv.py tests/test_deflated_sharpe.py -v after implementation.
```

### Session 2.3 — Integrate feature store and validation into pipeline

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 2: Feature Store.

The feature store core (feature_store/) and validation modules (analytics/cpcv.py, analytics/deflated_sharpe.py) are implemented. Now integrate them into the existing pipeline.

1. Modify config.py:
   - Add FEATURE_STORE_DIR: str = "feature_store" (relative to project root)
   - Add FEATURE_STORE_WRITE_ENABLED: bool = False (default off, opt-in)
   - Add FEATURE_STORE_SCHEMA_VERSION: int = 1
   - Add BACKTEST_VALIDATION_MODE: str = "rolling" (existing default; alternative: "cpcv")
   - Add BACKTEST_CPCV_N_GROUPS: int = 5
   - Add BACKTEST_CPCV_K_SPLITS: int = 2
   - Add BACKTEST_PURGE_DAYS: int = 5
   - Add BACKTEST_EMBARGO_DAYS: int = 3
   - Add BACKTEST_USE_FEATURE_STORE: bool = False

2. Modify scan_engine.py:
   - Read the file to find where candidate rows are assembled (after build_candidate_row and the results DataFrame is built)
   - After candidates are assembled, if cfg.FEATURE_STORE_WRITE_ENABLED:
     - Build a TrendFeatures DataFrame from candidate columns (TrendScore, AVWAP_Slope, Sector, etc.)
     - Build an AVWAPFeatures DataFrame from setup context columns
     - Call feature_store.write() for each feature type
   - Wrap in try/except — feature store writes must never break the scan (fail-open)

3. Modify backtest_sweep.py:
   - Read the file to understand run_sweep() and build_summary_row()
   - In run_sweep(): check cfg.BACKTEST_VALIDATION_MODE
     - If "rolling": use existing compute_walk_forward_splits() (no change)
     - If "cpcv": use generate_cpcv_splits() from analytics/cpcv.py with the configured parameters
   - In build_summary_row() or build_leaderboard():
     - After computing Sharpe for each run, also compute deflated_sharpe_ratio() using:
       - observed_sharpe = the run's Sharpe
       - n_trials = total number of parameter combinations in the sweep
       - variance_sharpe = variance of Sharpe across all runs in the sweep
       - T = number of return observations for the run
     - Add "deflated_sharpe_pvalue" column to the summary

4. Modify backtest_engine.py:
   - Read the file to find where indicators are computed for each session date
   - If cfg.BACKTEST_USE_FEATURE_STORE and feature store has data for the date:
     - Read from feature store instead of recomputing (optimization, not behavioral change)
     - Fall back to inline computation if feature store miss
   - This is a performance optimization — wrap behind the flag, fail-open to inline computation

5. Run the full test suite: pytest tests/ -x --timeout=60

Do not over-engineer. Keep integrations minimal — just enough to write features and read them back.
```

### Session 2.4 — Commit Phase 2

```
Read docs/ALPHA_UPGRADE_PLAN.md Phase 2 verification checklist.

Verify all Phase 2 deliverables:
1. Run pytest tests/test_feature_store.py tests/test_cpcv.py tests/test_deflated_sharpe.py -v
2. Verify feature_store/ directory has all 6 modules (__init__, store, schemas, writers, readers, versioning)
3. Verify analytics/cpcv.py and analytics/deflated_sharpe.py exist
4. Verify config.py has all new feature store and validation flags
5. Verify scan_engine.py writes to feature store when FEATURE_STORE_WRITE_ENABLED=True
6. Verify backtest_sweep.py supports validation_mode="cpcv" and includes deflated_sharpe_pvalue
7. Run pytest tests/ -x --timeout=60 for full regression

If everything passes, create a commit with message:
"Add feature store infrastructure and CPCV/DSR validation (Phase 2)"

Update docs/ALPHA_UPGRADE_PLAN.md: change Phase 2 status from TODO to DONE and check all task checkboxes.
```

---

## Phase 3: Cross-Sectional Scoring

### Session 3.1 — Cross-sectional module + integration + tests

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 3: Cross-Sectional Scoring.

Implement cross-sectional scoring end-to-end. This is a medium-scope phase — do it all in one session.

1. Create analytics/cross_sectional.py:
   - compute_z_scores(df, columns) -> DataFrame:
     - For each column in columns, compute z-score = (value - mean) / std
     - Handle edge cases: if std == 0 or len(df) <= 1, return 0.0 for all z-scores
     - Handle NaN values: exclude from mean/std computation, fill NaN z-scores with 0.0
   - compute_percentile_ranks(df, columns) -> DataFrame:
     - For each column, compute percentile rank (0.0 to 1.0) using pandas rank(pct=True)
   - composite_rank(trend_z, dist_z, slope_z, weights=None) -> float:
     - weights default: {"trend": 0.4, "dist": 0.3, "slope": 0.3}
     - return weights["trend"] * trend_z - weights["dist"] * dist_z + weights["slope"] * slope_z
     - dist_pct is inverted: closer to AVWAP (lower dist) = better
   - apply_cross_sectional_scoring(candidates_df, features, top_decile=0.1, hard_floor_trend=5.0) -> DataFrame:
     - Compute z-scores and percentile ranks for the specified features
     - Compute Composite_Rank for each row
     - Filter to top decile by Composite_Rank (keep top top_decile fraction)
     - BUT: always enforce hard_floor_trend — remove any candidate below hard_floor_trend regardless of rank
     - Return enriched DataFrame with new columns: TrendScore_Zscore, TrendScore_Pctile, DistPct_Zscore, Composite_Rank

2. Modify scan_engine.py:
   - Read the file to understand the candidate assembly flow and CANDIDATE_COLUMNS list
   - Add new columns to CANDIDATE_COLUMNS: TrendScore_Zscore, TrendScore_Pctile, DistPct_Zscore, Composite_Rank
   - After all candidate rows are built (after the main loop that calls build_candidate_row):
     - If cfg.CROSS_SECTIONAL_ENABLED:
       - Call apply_cross_sectional_scoring() on the full candidates DataFrame
       - This replaces the existing absolute threshold filtering for candidate selection
     - If not enabled: fill the new columns with NaN (backward compatible)
   - Bump SchemaVersion from 1 to 2 when cross-sectional columns are present

3. Modify backtest_engine.py:
   - Read the file to find _scan_as_of() or equivalent function that produces candidates per date
   - If cfg.CROSS_SECTIONAL_ENABLED: pipe daily candidates through apply_cross_sectional_scoring()
   - Ensure _validate_candidates() handles both SchemaVersion 1 and 2

4. Modify config.py:
   - Add CROSS_SECTIONAL_ENABLED: bool = False (default off)
   - Add CROSS_SECTIONAL_TOP_DECILE: float = 0.1 (top 10%)
   - Add CROSS_SECTIONAL_FEATURES: list = ["TrendScore", "Entry_DistPct", "AVWAP_Slope"]
   - Add CROSS_SECTIONAL_HARD_FLOOR_TREND_SCORE: float = 5.0

5. Modify feature_store/writers.py:
   - Add write_cross_sectional_distributions(date, stats_dict) that saves the day's mean, std, and percentile breakpoints for reproducibility

6. Create tests/test_cross_sectional.py:
   - Test z-score computation with known values
   - Test percentile rank computation
   - Test composite_rank formula
   - Test top-decile filtering (50 candidates -> ~5 selected)
   - Test hard floor enforcement (candidate with high rank but trend_score=3.0 is excluded)
   - Test single candidate edge case (fall back to absolute thresholds)
   - Test all identical values (std=0, all z-scores=0)
   - Test NaN handling

Run pytest tests/test_cross_sectional.py -v then pytest tests/ -x --timeout=60 for full regression.
```

### Session 3.2 — Commit Phase 3

```
Read docs/ALPHA_UPGRADE_PLAN.md Phase 3 verification checklist.

Verify all Phase 3 deliverables:
1. Run pytest tests/test_cross_sectional.py -v
2. Verify analytics/cross_sectional.py exists with all specified functions
3. Verify scan_engine.py adds cross-sectional columns and filters by Composite_Rank when enabled
4. Verify backtest_engine.py pipes candidates through cross-sectional scoring when enabled
5. Verify config.py has CROSS_SECTIONAL_ENABLED, CROSS_SECTIONAL_TOP_DECILE, CROSS_SECTIONAL_FEATURES, CROSS_SECTIONAL_HARD_FLOOR_TREND_SCORE
6. Verify SchemaVersion bumps to 2 when cross-sectional is enabled
7. Verify backward compat: SchemaVersion=1 backtests still work when flag is off
8. Run pytest tests/ -x --timeout=60

If everything passes, create a commit with message:
"Add cross-sectional scoring with universe-relative rankings (Phase 3)"

Update docs/ALPHA_UPGRADE_PLAN.md: change Phase 3 status from TODO to DONE and check all task checkboxes.
```

---

## Phase 4: Multi-Factor Regime Model

### Session 4.1 — E2 features and classifier

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 4: Multi-Factor Regime Model.

Build the E2 regime features and classifier. Read the existing E1 implementation first to understand the patterns.

1. Read analytics/regime_e1_features.py thoroughly — understand RegimeFeatureSet, compute_regime_features(), and how SPY data is extracted and normalized.

2. Read analytics/regime_e1_classifier.py thoroughly — understand classify_regime(), the threshold constants, and the RegimeClassification output.

3. Create analytics/regime_e2_features.py:
   - Import and extend E1's RegimeFeatureSet (add new fields with defaults for backward compat):
     - credit_spread_z: float = 0.0 (HYG/LQD ratio z-score)
     - vix_term_structure: float = 0.0 (VIX - VIX3M, approximated as VIX short-term vs long-term vol)
     - gld_relative_strength: float = 0.0
     - tlt_relative_strength: float = 0.0
   - compute_e2_features(history_df, spy_ticker="SPY", lookback=63) -> RegimeFeatureSet:
     - Compute all E1 features (delegate to E1's compute function or recompute)
     - Compute credit_spread_z: HYG_close / LQD_close ratio, z-score over lookback period
     - Compute GLD and TLT 20-day relative strength vs SPY
     - Handle missing tickers gracefully (if HYG/LQD/GLD/TLT missing, leave defaults of 0.0)
   - BENCHMARK_TICKERS in scan_engine.py already includes HYG, LQD, GLD, TLT — verify this

4. Create analytics/regime_e2_classifier.py:
   - classify_regime_e2(features: RegimeFeatureSet) -> dict:
     - Returns {"regime_label": str, "regime_score": float, "confidence": float, "factors": dict}
     - regime_score is continuous 0.0 (full risk-off) to 1.0 (full risk-on)
     - Multi-factor weighted score:
       - trend_component (0.30 weight): based on SPY vs SMA200/SMA50, normalized to 0-1
       - volatility_component (0.25 weight): inverse of realized vol, normalized to 0-1
       - credit_component (0.20 weight): credit_spread_z mapped to 0-1 (positive z = tight spreads = risk-on)
       - breadth_component (0.15 weight): % of universe above 50-SMA, normalized to 0-1
       - drawdown_component (0.10 weight): inverse of current drawdown depth, 0-1
     - regime_label derived from regime_score: >= 0.65 "RISK_ON", >= 0.35 "NEUTRAL", < 0.35 "RISK_OFF"
     - confidence = 1.0 - 2 * abs(regime_score - nearest_threshold) (higher near thresholds = lower confidence)
     - factors dict includes each component's raw value and weighted contribution

5. Create tests/test_regime_e2_features.py:
   - Test with mock OHLCV data containing SPY, HYG, LQD, GLD, TLT
   - Test graceful degradation when HYG/LQD are missing (should use defaults)
   - Test credit_spread_z calculation with known values

6. Create tests/test_regime_e2_classifier.py:
   - Test regime_score boundaries (0.65 -> RISK_ON, 0.35 -> NEUTRAL, 0.34 -> RISK_OFF)
   - Test that all factor weights sum to 1.0
   - Test confidence calculation
   - Test with extreme inputs (all bullish, all bearish, mixed)

Run pytest tests/test_regime_e2_features.py tests/test_regime_e2_classifier.py -v after implementation.
```

### Session 4.2 — Transition smoothing + risk controls integration

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 4: Regime Transition Smoothing and Backward Compatibility sections.

The E2 features and classifier are implemented. Now add transition smoothing and wire into risk controls.

1. Create analytics/regime_transition.py:
   - RegimeTransitionDetector class exactly as specified in the plan:
     - __init__(smoothing_days=5)
     - update(raw_regime, confidence, date) -> str
     - Requires N consecutive days of new regime before transitioning
     - Returns sticky (previous) regime during transition periods
   - reset() method to clear history
   - get_transition_state() -> dict returning {"current_regime": str, "pending_regime": str | None, "consecutive_days": int, "is_transitioning": bool}

2. Modify portfolio/risk_controls.py:
   - Read the file, find _regime_to_throttle() function
   - Add a new code path: if cfg.REGIME_MODEL_VERSION == "e2":
     - Read regime_score (continuous 0.0-1.0) instead of discrete label
     - Interpolate risk_multiplier: risk_mult = regime_score (linear mapping: 0.0 = full block, 1.0 = full risk)
     - Apply low-confidence haircut as E1 already does
   - The E1 path remains unchanged and is the default

3. Modify config.py:
   - Add REGIME_MODEL_VERSION: str = "e1" (default unchanged)
   - Add REGIME_TRANSITION_SMOOTHING_DAYS: int = 5
   - Add REGIME_CREDIT_SPREAD_LOOKBACK: int = 63

4. Modify scan_engine.py:
   - Verify BENCHMARK_TICKERS includes HYG, LQD, GLD, TLT (it should already)
   - In the history backfill section, ensure these tickers are always fetched even if not in the scan universe

5. Modify feature_store/writers.py:
   - Add write_regime_e2_features(date, features_dict) to persist E2 regime features
   - Follow the same pattern as existing feature writes

6. Create tests/test_regime_transition.py:
   - Test sticky behavior: alternate RISK_ON/RISK_OFF every day for 10 days — regime should NOT flip
   - Test transition: 5 consecutive RISK_OFF days after RISK_ON — regime should flip on day 5
   - Test reset clears history
   - Test get_transition_state during and after transition

7. Run full test suite: pytest tests/ -x --timeout=60

Do not change any E1 behavior. E1 must remain the default.
```

### Session 4.3 — Commit Phase 4

```
Read docs/ALPHA_UPGRADE_PLAN.md Phase 4 verification checklist.

Verify all Phase 4 deliverables:
1. Run pytest tests/test_regime_e2_features.py tests/test_regime_e2_classifier.py tests/test_regime_transition.py -v
2. Verify analytics/regime_e2_features.py, regime_e2_classifier.py, and regime_transition.py exist
3. Verify portfolio/risk_controls.py handles REGIME_MODEL_VERSION="e2" with continuous interpolation
4. Verify config.py has REGIME_MODEL_VERSION, REGIME_TRANSITION_SMOOTHING_DAYS, REGIME_CREDIT_SPREAD_LOOKBACK
5. Verify E1 is still the default (REGIME_MODEL_VERSION="e1")
6. Verify E2 degrades gracefully when HYG/LQD data is missing
7. Run pytest tests/ -x --timeout=60 for full regression

If everything passes, create a commit with message:
"Add multi-factor regime model E2 with transition smoothing (Phase 4)"

Update docs/ALPHA_UPGRADE_PLAN.md: change Phase 4 status from TODO to DONE and check all task checkboxes.
```

---

## Phase 5: Correlation-Aware Sizing

### Session 5.1 — Correlation matrix + sizing penalty + tests

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 5: Correlation-Aware Sizing.

Implement correlation-aware sizing end-to-end.

1. Read execution_v2/sizing.py to understand the current compute_size_shares() function and its parameters.
2. Read execution_v2/buy_loop.py to understand how sizing is called during the entry flow.
3. Read analytics/risk_attribution.py to understand the attribution event format.

4. Create analytics/correlation_matrix.py:
   - compute_rolling_correlation(ohlcv_df, symbols, lookback_days=60) -> pd.DataFrame:
     - Compute pairwise correlation matrix of daily returns for the given symbols
     - Use the last lookback_days of data
     - Returns a symmetric DataFrame with symbols as both index and columns
     - Handle missing data: if a symbol has < lookback_days/2 data points, exclude it from the matrix
   - get_sector_exposure(open_positions, candidate_sector, sector_map) -> dict:
     - Returns {"sector": str, "current_exposure_pct": float, "would_be_exposure_pct": float}

5. Create execution_v2/correlation_sizing.py:
   - correlation_penalty(candidate_symbol, open_positions, corr_matrix, threshold=0.6, max_penalty=0.5) -> float:
     - Exactly as specified in the plan
     - Returns 0.0 if no open positions or candidate not in matrix
     - Returns penalty in [0.0, max_penalty] based on average absolute correlation with open positions above threshold
   - check_sector_cap(candidate_sector, open_positions, sector_map, max_sector_pct=0.3, gross_exposure=None) -> tuple[bool, str]:
     - Returns (allowed: bool, reason: str)
     - If adding this candidate would push sector exposure above max_sector_pct, return (False, "sector cap exceeded: {sector} at {pct}%")

6. Modify execution_v2/sizing.py:
   - Add optional correlation_penalty parameter to compute_size_shares() (default 0.0)
   - Modify the formula: dollar_alloc = account_equity * base_risk_pct * risk_scale * (1.0 - correlation_penalty)
   - This is backward compatible — default penalty of 0.0 means no change

7. Modify execution_v2/buy_loop.py:
   - Before calling compute_size_shares(), if cfg.CORRELATION_AWARE_SIZING_ENABLED:
     - Load or compute the correlation matrix for current candidates + open positions
     - Call correlation_penalty() to get the penalty value
     - Call check_sector_cap() — if blocked, skip entry (log as BLOCK in portfolio decisions)
     - Pass penalty to compute_size_shares()
   - Wrap behind feature flag, fail-open if correlation computation fails

8. Modify backtest_engine.py:
   - Same logic in the entry fill path: compute correlation penalty from existing positions before sizing
   - Gate behind cfg.CORRELATION_AWARE_SIZING_ENABLED

9. Modify config.py:
   - Add CORRELATION_AWARE_SIZING_ENABLED: bool = False
   - Add CORRELATION_LOOKBACK_DAYS: int = 60
   - Add CORRELATION_PENALTY_THRESHOLD: float = 0.6
   - Add MAX_SECTOR_EXPOSURE_PCT: float = 0.3
   - Add MAX_CORRELATED_CLUSTER_EXPOSURE_PCT: float = 0.4

10. Modify analytics/risk_attribution.py:
    - Add correlation_penalty field to attribution events (default 0.0 for backward compat)

11. Modify feature_store/writers.py:
    - Add write_correlation_matrix(date, corr_df) to persist daily matrices

12. Create tests/test_correlation_matrix.py:
    - Test with known returns data (perfectly correlated, uncorrelated, anti-correlated)
    - Test missing data handling
    - Test sector exposure computation

13. Create tests/test_correlation_sizing.py:
    - Test penalty = 0.0 when no open positions
    - Test penalty = 0.0 when correlation below threshold
    - Test penalty scales linearly above threshold up to max_penalty
    - Test sector cap BLOCK logic
    - Test sector cap ALLOW logic

Run pytest tests/test_correlation_matrix.py tests/test_correlation_sizing.py -v then pytest tests/ -x --timeout=60.
```

### Session 5.2 — Commit Phase 5

```
Read docs/ALPHA_UPGRADE_PLAN.md Phase 5 verification checklist.

Verify all Phase 5 deliverables:
1. Run pytest tests/test_correlation_matrix.py tests/test_correlation_sizing.py -v
2. Verify analytics/correlation_matrix.py and execution_v2/correlation_sizing.py exist
3. Verify execution_v2/sizing.py accepts correlation_penalty parameter
4. Verify buy_loop.py computes and passes correlation penalty when flag is on
5. Verify backtest_engine.py applies correlation sizing when flag is on
6. Verify config.py has all correlation config flags
7. Verify risk attribution events include correlation_penalty field
8. Verify feature flag off = identical sizing behavior to before
9. Run pytest tests/ -x --timeout=60

If everything passes, create a commit with message:
"Add correlation-aware sizing with sector caps (Phase 5)"

Update docs/ALPHA_UPGRADE_PLAN.md: change Phase 5 status from TODO to DONE and check all task checkboxes.
```

---

## Phase 6: Dynamic Gross Exposure

### Session 6.1 — Dynamic exposure module + integration + tests

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 6: Dynamic Gross Exposure.

Implement dynamic gross exposure end-to-end.

1. Read portfolio/risk_controls.py to understand build_risk_controls() and how max_gross_exposure is currently set.
2. Read analytics/risk_attribution.py to understand attribution event format.

3. Create portfolio/dynamic_exposure.py:
   - compute_realized_portfolio_vol(daily_pnl_series, lookback_days=20) -> float:
     - Compute annualized volatility from daily P&L returns
     - annualized = daily_std * sqrt(252)
     - Handle edge cases: < 5 data points returns 0.0, all zeros returns 0.0
   - compute_target_exposure(realized_portfolio_vol, target_vol, regime_multiplier, floor=0.2, ceiling=1.0) -> float:
     - Exactly as specified in the plan
     - If realized_vol <= 0: return ceiling * regime_multiplier
     - raw_target = target_vol / realized_portfolio_vol
     - regime_adjusted = raw_target * regime_multiplier
     - Return clamped between floor and ceiling
   - DynamicExposureResult dataclass:
     - target_exposure: float
     - realized_vol: float
     - regime_multiplier: float
     - raw_target: float
     - clamped: bool (True if floor or ceiling was applied)

4. Modify portfolio/risk_controls.py:
   - In build_risk_controls(): if cfg.DYNAMIC_EXPOSURE_ENABLED:
     - Compute realized portfolio vol from recent equity curve / P&L data
     - Get regime_multiplier from E1 or E2 model (whatever is configured)
     - Call compute_target_exposure() to get the dynamic target
     - Use this as max_gross_exposure instead of the static config value
   - The drawdown guardrail remains an independent kill switch (unchanged)

5. Modify execution_v2/buy_loop.py:
   - Ensure the dynamic exposure target flows through to order quantity decisions
   - The buy loop already respects max_gross_exposure from risk controls — verify this path works

6. Modify backtest_engine.py:
   - Find where max_gross_exposure_pct is used (~line 416)
   - If cfg.DYNAMIC_EXPOSURE_ENABLED: compute it dynamically each day from the equity curve built so far
   - Use compute_realized_portfolio_vol on the trailing equity curve returns

7. Modify config.py:
   - Add DYNAMIC_EXPOSURE_ENABLED: bool = False
   - Add TARGET_PORTFOLIO_VOL: float = 0.15 (15% annualized)
   - Add MAX_GROSS_EXPOSURE_CEILING: float = 1.0
   - Add MIN_GROSS_EXPOSURE_FLOOR: float = 0.2
   - Add PORTFOLIO_VOL_LOOKBACK_DAYS: int = 20

8. Modify analytics/risk_attribution.py:
   - Add target_exposure, actual_exposure, portfolio_vol fields to attribution events (defaults for backward compat)

9. Create tests/test_dynamic_exposure.py:
   - Test vol calculation with known daily returns (e.g., daily std = 0.01 -> annualized ~15.87%)
   - Test target exposure: realized_vol=0.20, target=0.15 -> raw target=0.75
   - Test floor clamping: extremely high vol -> target hits floor
   - Test ceiling clamping: extremely low vol -> target hits ceiling
   - Test regime interaction: regime_multiplier=0.5 halves the target
   - Test zero vol edge case
   - Test < 5 data points returns vol=0.0

Run pytest tests/test_dynamic_exposure.py -v then pytest tests/ -x --timeout=60.
```

### Session 6.2 — Commit Phase 6

```
Read docs/ALPHA_UPGRADE_PLAN.md Phase 6 verification checklist.

Verify all Phase 6 deliverables:
1. Run pytest tests/test_dynamic_exposure.py -v
2. Verify portfolio/dynamic_exposure.py exists with compute_realized_portfolio_vol and compute_target_exposure
3. Verify risk_controls.py uses dynamic exposure when DYNAMIC_EXPOSURE_ENABLED=True
4. Verify backtest_engine.py computes dynamic exposure per day when enabled
5. Verify config.py has DYNAMIC_EXPOSURE_ENABLED, TARGET_PORTFOLIO_VOL, MAX_GROSS_EXPOSURE_CEILING, MIN_GROSS_EXPOSURE_FLOOR, PORTFOLIO_VOL_LOOKBACK_DAYS
6. Verify attribution events include portfolio vol and target exposure
7. Verify feature flag off = identical behavior to before
8. Run pytest tests/ -x --timeout=60

If everything passes, create a commit with message:
"Add dynamic gross exposure with vol-targeting (Phase 6)"

Update docs/ALPHA_UPGRADE_PLAN.md: change Phase 6 status from TODO to DONE and check all task checkboxes.
```

---

## Phase 7: Survivorship-Clean Backtesting

### Session 7.1 — Historical constituency + corporate actions

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 7: Survivorship-Clean Backtesting.

Read universe.py to understand the current load_r3k_universe_from_iwv() function and caching strategy.

1. Create universe/historical_constituency.py:
   - load_universe_as_of(date_str, constituency_path=None) -> pd.DataFrame:
     - Looks in constituency_path (default: universe/historical/) for dated CSV files
     - Finds the most recent file where file_date <= requested date (point-in-time, never future)
     - Returns DataFrame with columns: Ticker, Sector, Weight (matching current universe format)
     - If no historical data available, falls back to current universe with a warning
   - list_available_dates(constituency_path=None) -> list[str]:
     - Returns sorted list of available historical snapshot dates
   - Expected file format: universe/historical/YYYY-MM-DD.csv with columns Ticker, Sector, Weight

2. Create universe/corporate_actions.py:
   - CorporateAction frozen dataclass as specified in the plan (symbol, action_type, effective_date, ratio, acquirer)
   - load_corporate_actions(path=None) -> list[CorporateAction]:
     - Loads from CSV at path (default: universe/corporate_actions.csv)
     - Columns: symbol, action_type, effective_date, ratio, acquirer
   - adjust_prices_for_splits(ohlcv_df, actions) -> pd.DataFrame:
     - For each split action: multiply pre-split OHLCV prices by 1/ratio and volume by ratio
     - Only adjusts dates before effective_date
     - Returns adjusted DataFrame (does not modify in place)
   - get_delistings(actions, as_of_date=None) -> list[str]:
     - Returns symbols delisted on or before as_of_date

3. Modify universe.py:
   - Add load_universe_as_of(date_str) function that delegates to historical_constituency.load_universe_as_of()
   - Keep existing load_r3k_universe_from_iwv() unchanged

4. Modify cache_store.py:
   - In upsert_history(): if cfg.BACKTEST_APPLY_SPLIT_ADJUSTMENTS and corporate actions file exists:
     - After merging new data, apply adjust_prices_for_splits()
     - This ensures the OHLCV cache is always split-adjusted

5. Modify config.py:
   - Add BACKTEST_HISTORICAL_CONSTITUENCY_PATH: str = "universe/historical"
   - Add BACKTEST_CORPORATE_ACTIONS_PATH: str = "universe/corporate_actions.csv"
   - Add BACKTEST_APPLY_SPLIT_ADJUSTMENTS: bool = False

6. Create tests/test_historical_constituency.py:
   - Test point-in-time loading: create 3 dated CSVs, query date between 2nd and 3rd, verify 2nd is returned
   - Test fallback when no historical data exists
   - Test empty directory handling

7. Create tests/test_corporate_actions.py:
   - Test split adjustment: price 100 with 2-for-1 split -> pre-split prices become 50
   - Test volume adjustment: 1000 shares -> 2000 shares pre-split
   - Test multiple splits on same symbol
   - Test delisting detection

Run pytest tests/test_historical_constituency.py tests/test_corporate_actions.py -v.
```

### Session 7.2 — Point-in-time earnings + backtest integration

```
Read docs/ALPHA_UPGRADE_PLAN.md, specifically Phase 7: the remaining tasks.

Historical constituency and corporate actions modules are implemented. Now add point-in-time earnings and wire everything into the backtest engine.

1. Create universe/point_in_time_earnings.py:
   - load_earnings_calendar(path=None) -> pd.DataFrame:
     - Loads from Parquet at path (default: universe/earnings_calendar.parquet)
     - Columns: symbol, earnings_date, is_before_market (bool)
     - If file doesn't exist, return empty DataFrame
   - is_near_earnings_pit(symbol, as_of_date, calendar_df, window_days=3) -> bool:
     - Check if symbol has earnings within window_days of as_of_date
     - Uses only earnings dates known as of as_of_date (point-in-time: exclude future-dated entries that were announced after as_of_date)
     - This replaces the live yfinance lookup in backtest mode

2. Modify backtest_engine.py:
   - Read the file to find universe loading (~line 491-503) and earnings filtering
   - Universe loading: if cfg.BACKTEST_USE_DATED_UNIVERSE_SNAPSHOTS (flag already exists but is unused):
     - Use load_universe_as_of(session_date) instead of static load_universe()
     - This means each backtest day uses the R3K membership as of that date
   - Earnings filtering: if in backtest mode and earnings calendar exists:
     - Use is_near_earnings_pit() instead of the live is_near_earnings_cached()
   - Delistings: if corporate actions are loaded:
     - Force-exit any open position in a delisted symbol at last available price

3. Modify scan_engine.py:
   - In is_near_earnings_cached() (~line 402): add a code path for backtest mode
   - If BACKTEST_POINT_IN_TIME_EARNINGS_PATH is set and file exists, use point-in-time lookup
   - Otherwise use existing live yfinance logic (unchanged)

4. Modify config.py:
   - Add BACKTEST_POINT_IN_TIME_EARNINGS_PATH: str = "universe/earnings_calendar.parquet"

5. Extend provenance.py or backtest_engine.py provenance:
   - Add constituency_source (path to historical constituency used) to provenance metadata
   - Add corporate_actions_hash (SHA256 of corporate actions CSV if used)

6. Create tests/test_point_in_time_earnings.py:
   - Test is_near_earnings_pit with known earnings date within window -> True
   - Test earnings date outside window -> False
   - Test point-in-time: earnings announced on 2024-03-20 for date 2024-03-25 should NOT be visible when queried as-of 2024-03-19
   - Test missing calendar file -> empty DataFrame -> all symbols pass (fail-open)

7. Run full test suite: pytest tests/ -x --timeout=60

Do not change any live (non-backtest) behavior. All changes are gated behind backtest config flags.
```

### Session 7.3 — Commit Phase 7

```
Read docs/ALPHA_UPGRADE_PLAN.md Phase 7 verification checklist.

Verify all Phase 7 deliverables:
1. Run pytest tests/test_historical_constituency.py tests/test_corporate_actions.py tests/test_point_in_time_earnings.py -v
2. Verify universe/historical_constituency.py, corporate_actions.py, and point_in_time_earnings.py exist
3. Verify universe.py has load_universe_as_of() function
4. Verify backtest_engine.py uses historical constituency when BACKTEST_USE_DATED_UNIVERSE_SNAPSHOTS=True
5. Verify backtest_engine.py uses point-in-time earnings when calendar file exists
6. Verify cache_store.py applies split adjustments when BACKTEST_APPLY_SPLIT_ADJUSTMENTS=True
7. Verify config.py has all Phase 7 flags
8. Verify provenance includes constituency_source and corporate_actions_hash
9. Verify no live (non-backtest) behavior changed
10. Run pytest tests/ -x --timeout=60

If everything passes, create a commit with message:
"Add survivorship-clean backtesting with historical constituency (Phase 7)"

Update docs/ALPHA_UPGRADE_PLAN.md: change Phase 7 status from TODO to DONE and check all task checkboxes.
```

---

## Final Verification Session

```
Read docs/ALPHA_UPGRADE_PLAN.md. All 7 phases should be marked DONE.

Run the complete verification:

1. Full test suite: pytest tests/ -v --timeout=120
2. Verify all feature flags exist in config.py and default to OFF (except SLIPPAGE_LEDGER_ENABLED which defaults ON):
   - SLIPPAGE_LEDGER_ENABLED
   - FEATURE_STORE_WRITE_ENABLED
   - BACKTEST_USE_FEATURE_STORE
   - BACKTEST_VALIDATION_MODE
   - CROSS_SECTIONAL_ENABLED
   - REGIME_MODEL_VERSION
   - CORRELATION_AWARE_SIZING_ENABLED
   - DYNAMIC_EXPOSURE_ENABLED
   - BACKTEST_USE_DATED_UNIVERSE_SNAPSHOTS
   - BACKTEST_APPLY_SPLIT_ADJUSTMENTS
3. Verify no existing behavior changes when all flags are OFF — the system should be identical to pre-upgrade
4. List all new files created across all phases
5. List all modified files

Report the results. Do NOT create a commit — this is verification only.
```

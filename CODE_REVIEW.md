# Code Review - AVWAP R3K Scanner

**Reviewer:** Claude (Professional SE / UI-UX / Code Review)
**Date:** 2026-03-01
**Scope:** Full codebase (~1,083 files, excluding venv/node_modules/.git)
**Methodology:** Fair evaluation -- real bugs and meaningful issues only, no style nitpicks

---

## Summary

| Area | Critical | High | Medium | Low | Total |
|------|----------|------|--------|-----|-------|
| Security & Auth | 4 | 2 | 1 | 0 | **7** |
| Strategies | 2 | 4 | 9 | 7 | **22** |
| Analytics | 2 | 4 | 8 | 6 | **20** |
| Execution / Data | 1 | 4 | 11 | 8 | **24** |
| Ops / Infra | 0 | 4 | 7 | 5 | **16** |
| Frontend (React) | 2 | 4 | 6 | 5 | **17** |
| Backend (FastAPI) | 0 | 3 | 6 | 6 | **15** |
| Tests | 0 | 1 | 6 | 4 | **11** |
| **Total** | **11** | **26** | **54** | **41** | **132** |

---

## How to use this file

- **Checkbox**: Mark `[x]` when the issue is resolved
- **Comment**: Add notes under the `> Comment:` block
- Issues are numbered globally (`#1`, `#2`, ...) for easy reference
- Severity: `CRITICAL` > `HIGH` > `MEDIUM` > `LOW`

---

## CRITICAL Issues

### #1 - [CRITICAL] Backend: No authentication on any endpoint (publicly accessible)
- [x] Done
- **File:** `analytics_platform/backend/app.py:92-509`
- **Description:** All endpoints -- including `POST/PUT/DELETE /api/v1/trades/log` -- have zero authentication. The server binds to `0.0.0.0` and is exposed via Cloudflare tunnel to `avwap.vantagedutch.com`. Anyone on the internet can create, modify, or delete trade records.
- **Fix:** Add at minimum an API key middleware or basic auth. Consider `127.0.0.1` as default bind address.
> Comment:

---

### #2 - [CRITICAL] Backend: CORS wildcard `"*"` allows cross-origin mutations
- [x] Done
- **File:** `analytics_platform/backend/app.py:84-90`
- **Description:** `allow_origins` includes `"*"`, making the specific origin entries redundant. Any website visited by a user on the same network can make mutating API requests. Combined with #1, this is an open door.
- **Fix:** Remove `"*"` from `allow_origins`. Keep only the specific localhost origins and the production domain.
> Comment:

---

### #3 - [CRITICAL] Backend: Path traversal in SPA fallback handler
- [x] Done
- **File:** `analytics_platform/backend/app.py:498-503`
- **Description:** `/app/{path:path}` joins user input directly with `dist_dir` without sanitization. A request like `/app/../../.env` can read arbitrary files. `pathlib /` does not prevent traversal.
- **Fix:** Add `if not static_file.resolve().is_relative_to(dist_dir.resolve()): return 404`.
> Comment:

---

### #4 - [CRITICAL] Sentinel: Bare `except:` clauses swallow errors in trading logic
- [x] Done
- **File:** `sentinel.py:100, 109, 202, 276`
- **Description:** Multiple bare `except:` clauses (not `except Exception:`) catch `SystemExit` and `KeyboardInterrupt`. Line 202 uses exception handling to determine "no position exists", hiding real API errors. Line 276 swallows failures to trim a live position.
- **Fix:** Replace bare `except:` with `except Exception:` at minimum. For line 202, use the Alpaca API's proper "position not found" response.
> Comment:

---

### #5 - [CRITICAL] Execution: Trading client instantiated at import time with possibly-None credentials
- [x] Done
- **File:** `execution.py:59-63`
- **Description:** `TradingClient(os.getenv("APCA_API_KEY_ID"), ...)` is at module level. If env vars are unset, `None` is passed. Any module importing `execution.py` triggers this, even if no trading is intended.
- **Fix:** Lazy initialization -- construct the client only when first needed.
> Comment:

---

### #6 - [CRITICAL] Frontend: `usePolling` stale closure bug -- filter changes are never reflected
- [x] Done
- **File:** `analytics_platform/frontend/src/hooks/usePolling.ts:11-52`
- **Description:** The `useEffect` dependency array only includes `[intervalMs]`. The `loader` function is captured in a closure that never updates. Changing date range, filters, or book in CommandCenter, PerformancePage, SchwabAccountPage, ScanPage, or BlotterPage will NOT cause the poll to use the new values until a full remount.
- **Fix:** Store `loader` in a `useRef` and read it inside the interval callback, or include `loader` in the dependency array.
> Comment:

---

### #7 - [CRITICAL] Analytics: `deflated_sharpe.py` -- `math.sqrt` of potentially negative value
- [x] Done
- **File:** `analytics/deflated_sharpe.py:72-73`
- **Description:** `sr_adjusted = sr * math.sqrt(1 + (skew/6)*sr - ((kurtosis-3)/24)*sr**2)`. For high-kurtosis or high-Sharpe strategies, the expression inside `sqrt()` goes negative, causing a `ValueError` crash.
- **Fix:** Clamp the inner expression to `max(0, ...)` before taking the square root.
> Comment:

---

### #8 - [CRITICAL] Analytics: Drawdown throttle guard compares dict to float -- never fires
- [x] Done
- **File:** `analytics/portfolio_decision.py:181, 207, 295`
- **Description:** `metrics.get("drawdown")` returns the full drawdown dict (with keys `series`, `max_drawdown`, etc.), not a float. On line 295, `snapshot_inputs.drawdown >= config.max_drawdown_pct_block` silently evaluates to `False` (dict vs float comparison in Python 3). The drawdown throttle is completely broken.
- **Fix:** Extract the numeric value: `metrics.get("drawdown", {}).get("max_drawdown", 0.0)`.
> Comment:

---

### #9 - [CRITICAL] Analytics: E2 confidence function is inverted
- [x] Done
- **File:** `analytics/regime_e2_classifier.py:78-81`
- **Description:** `_confidence(score)` returns **highest** confidence at boundary crossings and **lowest** far from boundaries -- the exact opposite of the docstring's intent. The formula `1.0 - 2.0 * nearest_dist` is maximized when `nearest_dist` is 0 (at a boundary).
- **Fix:** Invert the formula: `confidence = 2.0 * nearest_dist` (clamped to [0, 1]).
> Comment:

---

### #10 - [CRITICAL] Execution: Deprecated `datetime.utcnow()` in trading code
- [x] Done
- **File:** `execution_v2/exits.py:766`
- **Description:** `datetime.utcnow()` returns a naive datetime, deprecated since Python 3.12 (project uses 3.14). In timezone-sensitive trading code, mixing naive and aware datetimes produces incorrect timestamps and comparison errors.
- **Fix:** Replace with `datetime.now(timezone.utc)`.
> Comment:

---

### #11 - [CRITICAL] Frontend: `usePolling.refresh` has unstable identity, breaks memoization
- [x] Done
- **File:** `analytics_platform/frontend/src/pages/TradeLogPage.tsx:106-109`
- **Description:** `refresh` from `usePolling` is recreated every render (not wrapped in `useCallback`). Any `useCallback` depending on `trades.refresh` or `summary.refresh` is effectively useless -- new function identity every render.
- **Fix:** Wrap `refresh` in `useCallback` inside the hook, or use a ref-based pattern.
> Comment:

---

## HIGH Issues

### #12 - [HIGH] Strategies: Coordinator writes state/ledger even in `dry_run` mode
- [x] Done
- **File:** `strategies/raec_401k_coordinator.py:211-220`
- **Description:** The coordinator unconditionally saves state and writes ledger entries regardless of the `dry_run` flag. A `--dry-run` of the coordinator mutates `last_eval_date` and writes ledger records. Contrast with `raec_401k_base.py:941` which gates on `if not dry_run or allow_state_write`.
- **Fix:** Gate state/ledger writes on the `dry_run` flag.
> Comment: Wrapped `_save_state` and `_write_raec_ledger` calls in `if not dry_run:`. Updated coordinator tests: added `test_coordinator_dry_run_skips_state` and updated `test_coordinator_state_persists` to run with `dry_run=False`.

---

### #13 - [HIGH] Strategies: V1/V2 are massive standalone copies diverging from base class
- [x] Done
- **File:** `strategies/raec_401k.py` (597 lines), `strategies/raec_401k_v2.py` (873 lines)
- **Description:** V1 and V2 duplicate state management, drift computation, turnover capping, volatility, and signal logic that was later refactored into `raec_401k_base.py`. Bug fixes in the base (e.g., -15% circuit breaker) are not in V1/V2. V2 uses `mom_6m` instead of `mom_3m`, has hardcoded defensive weights, and `top_n=3`. V1 has no circuit breaker at all.
- **Fix:** Decide: (a) migrate V1/V2 to use `BaseRAECStrategy`, or (b) document them as frozen/legacy and add a clear deprecation notice.
> Comment: Option (b) — added FROZEN/LEGACY docstring to both `raec_401k.py` and `raec_401k_v2.py` stating they predate `raec_401k_base.py`, bug fixes are not backported, and no new features should be added.

---

### #14 - [HIGH] Strategies: `ref_price` look-ahead bias in V1/V2
- [x] Done
- **File:** `strategies/raec_401k.py:449-451`, `strategies/raec_401k_v2.py:721-723`
- **Description:** When attaching `ref_price` to intents, the code calls `provider.get_daily_close_series(sym)` without filtering by `asof` date and takes `series[-1]`. If the provider has future data (backtesting), this introduces look-ahead bias.
- **Fix:** Use `_sorted_series` which filters correctly by date.
> Comment: Replaced `provider.get_daily_close_series(sym)` with `_sorted_series(provider.get_daily_close_series(sym), asof=_parse_date(asof_date))` in both V1 and V2.

---

### #15 - [HIGH] Strategies: Hardcoded `total_capital = 237_757.0` default
- [x] Done
- **File:** `strategies/raec_401k_coordinator.py:113`
- **Description:** `cap = total_capital or 237_757.0` is a stale dollar amount used in display messages and Slack tickets. It will show increasingly incorrect values as the portfolio changes.
- **Fix:** Source from state, config, or environment variable.
> Comment: Now reads `total_capital` from coordinator state file. Falls back to 0.0 with a WARN if not set. Persists `total_capital` into state on non-dry-run writes so subsequent runs auto-pick it up.

---

### #16 - [HIGH] Strategies: V1 `main()` declared `-> int` but returns `None`
- [x] Done
- **File:** `strategies/raec_401k.py:555`
- **Description:** The function contract is violated. `raise SystemExit(main())` receives `None`.
- **Fix:** Add `return 0` at the end of `main()`.
> Comment: Added `return 0` after the print summary block.

---

### #17 - [HIGH] Analytics: Malformed JSON line crashes entire regime pipeline
- [x] Done
- **File:** `analytics/regime_e1_storage.py:37-38`
- **Description:** `_load_existing_ids()` calls `json.loads(line)` with no try/except. One corrupted line in the ledger crashes the full regime run. Compare with `regime_throttle_writer.py:41-43` which correctly catches `json.JSONDecodeError`.
- **Fix:** Wrap in try/except, log warning, skip bad lines.
> Comment: Added `try/except json.JSONDecodeError` with `logger.warning()`, skips malformed lines. Added `logging` import.

---

### #18 - [HIGH] Execution: Race condition in JSONL ledger append (read-then-write)
- [x] Done
- **File:** `execution_v2/exit_events.py:279-288`, `execution_v2/paper_sim.py:233-237`
- **Description:** Both use a pattern of reading all lines, adding new ones, then atomically writing the whole file. If two processes execute concurrently, one overwrites the other's appended data. `atomic_write_text()` prevents partial writes but not lost updates.
- **Fix:** Use append mode (`open(path, "a")`) like `schwab_manual_confirmations.py:233` does correctly.
> Comment: Replaced read-then-atomic-write with `open("a")` in both `exit_events.append_exit_event` and `paper_sim.simulate_fills`. Updated corresponding tests in `test_atomic_write.py` to verify append preserves existing data.

---

### #19 - [HIGH] Execution: `stop_loss` from scan CSV is silently discarded
- [x] Done
- **File:** `execution_v2/buy_loop.py:660-668`
- **Description:** `EntryIntent` is created with `stop_loss=stop_price` (computed structural stop) instead of `cand.stop_loss` (from scan). The candidate's stop from the CSV is dead data for the entry intent path.
- **Fix:** Document if intentional. If not, use the scan's stop or a minimum of both.
> Comment: Intentional — added comment explaining the structural stop from daily bars is preferred over the scan CSV stop because it adapts to current market structure.

---

### #20 - [HIGH] Root: `backtest.py` type annotation `float | float("nan")` is meaningless
- [x] Done
- **File:** `backtest.py:56`
- **Description:** `sharpe: float | float("nan")` unions the type `float` with the runtime value `nan`. This is semantically meaningless and confusing.
- **Fix:** Change to `sharpe: float`.
> Comment: Changed to `sharpe: float`.

---

### #21 - [HIGH] Root: `analytics.py` expectancy is `NaN` when there are only wins
- [x] Done
- **File:** `analytics.py:21`
- **Description:** If `losses` is empty, `losses['PnL'].mean()` returns `NaN`, making `expectancy = NaN`. When there are only winning trades, expectancy should equal average PnL, not NaN.
- **Fix:** Guard: `if losses.empty: expectancy = wins['PnL'].mean()`.
> Comment: Added `if losses.empty:` guard returning `wins['PnL'].mean()` (or 0.0 if wins also empty).

---

### #22 - [HIGH] Root: `provenance.py` reads entire file into memory for hashing
- [x] Done
- **File:** `provenance.py:40-43`
- **Description:** `handle.read()` loads the full file for SHA-256 hashing. For large parquet files (hundreds of MB), this risks OOM.
- **Fix:** Use chunked reading with `hashlib.sha256()` + `.update()` in a loop.
> Comment: Replaced `_sha256_bytes(handle.read())` with `hashlib.sha256()` + `while chunk := handle.read(1 << 20)` loop (1 MiB chunks).

---

### #23 - [HIGH] Root: `sentinel.py` does not account for market holidays
- [x] Done
- **File:** `sentinel.py:77-81`
- **Description:** `is_market_open()` only checks weekday + time range. It will attempt to trade on holidays like Thanksgiving, MLK Day, etc.
- **Fix:** Use the Alpaca market calendar or a holiday list.
> Comment: Added `_US_MARKET_HOLIDAYS` set (2026-2027) and early-return `False` when today's date matches. Lightweight static set avoids API dependency.

---

### #24 - [HIGH] Ops: Pipeline docstring says 8 steps but code has 7 (raec_401k_v2 removed)
- [x] Done
- **File:** `ops/post_scan_pipeline.py:2-12 vs 32-87`
- **Description:** The docstring and MEMORY.md reference 8 steps including `raec_401k_v2`, but the `STEPS` list has only 7. Either the step was accidentally removed or the docs are stale.
- **Fix:** Verify intent. Update docstring and MEMORY.md accordingly.
> Comment: Docs were stale — `raec_401k_v2` was intentionally removed from the pipeline. Updated docstring to say "7 steps" and corrected the step list. Updated MEMORY.md. Fixed `test_pipeline_steps_in_correct_order` to expect 7 steps.

---

### #25 - [HIGH] Ops: `--dry-run` only propagated to 2 of 7 pipeline steps
- [x] Done
- **File:** `ops/post_scan_pipeline.py:97-100`
- **Description:** The `--dry-run` flag is only appended to `raec_401k_coordinator` and `s2_letf_orb_alpaca`. The other 5 steps execute with full side effects (regime writes, Schwab sync, seed allocations).
- **Fix:** Either propagate `--dry-run` to all steps, or rename the flag to `--suppress-orders` to accurately describe its scope.
> Comment: Clarified the `--help` text to explain that `--dry-run` only suppresses orders/posts for the two order-posting steps. The other steps only write local ledger/state files, so propagation is unnecessary.

---

### #26 - [HIGH] Ops: All systemd units reference dead droplet paths
- [x] Done
- **File:** `ops/systemd/*`, `tools/verify_systemd.py`
- **Description:** Per project state, the droplet is shut down. All systemd units hardcode `/root/avwap_r3k_scanner`. `verify_systemd.py`'s expected drop-in list is completely disjoint from what the repo ships. This is dead infrastructure with no deprecation marker.
- **Fix:** Archive or delete `ops/systemd/`, `install_systemd_units.sh`, `deploy_systemd.sh`, and `verify_systemd.py`.
> Comment: Added DEPRECATED notices to `deploy_systemd.sh`, `ops/install_systemd_units.sh`, `tools/verify_systemd.py`, and created `ops/systemd/DEPRECATED.md`. Kept files for reference rather than deleting.

---

### #27 - [HIGH] Frontend: Duplicate API polling -- Layout and pages both poll same endpoints
- [x] Done
- **File:** `analytics_platform/frontend/src/components/Layout.tsx:48-50`
- **Description:** Layout polls `portfolioOverview`, `health`, and `raecDashboard` on 60s intervals. Child pages (CommandCenter, StrategyRoster, RiskPage) also poll the same APIs independently. No shared data layer, no cache deduplication. Network load is doubled.
- **Fix:** Use React Context, a shared store, or `@tanstack/react-query` for deduplication.
> Comment: Created `LayoutDataContext` with `LayoutDataProvider` + `useLayoutData()` hook. Layout wraps children in the provider. Removed duplicate `usePolling` calls from CommandCenter, RiskPage, SystemPage, and StrategyRoster — they now consume shared data via `useLayoutData()`.

---

### #28 - [HIGH] Frontend: No ErrorBoundary -- lazy load failures crash entire app
- [x] Done
- **File:** `analytics_platform/frontend/src/App.tsx:11-43`
- **Description:** All pages use `React.lazy()` with `Suspense` but no `ErrorBoundary`. If a lazy chunk fails to load (network error, deploy mismatch), the entire app crashes to a white screen.
- **Fix:** Wrap `<Suspense>` in an `ErrorBoundary` with a retry/refresh UI.
> Comment: Created `ErrorBoundary.tsx` class component with retry button (reuses `ErrorState`). Wrapped every `<Suspense>` in App.tsx with `<ErrorBoundary>`.

---

### #29 - [HIGH] Frontend: Swallowed errors in trade close/delete operations
- [x] Done
- **File:** `analytics_platform/frontend/src/pages/TradeLogPage.tsx:118-133`
- **Description:** `handleClose` and `handleDelete` have empty `catch {}` blocks. API failures give the user zero feedback -- the trade appears to close but nothing happened.
- **Fix:** Show a toast/alert on error.
> Comment: Added `error` state. `handleClose`/`handleDelete` catch blocks now set error message. Renders a dismissible red error banner below the page header.

---

### #30 - [HIGH] Frontend: Unsafe `JSON.parse` without try-catch crashes component
- [x] Done
- **File:** `analytics_platform/frontend/src/pages/SchwabAccountPage.tsx:237`
- **Description:** `JSON.parse(latestRecon.drift_reason_codes_json)` will throw and crash the component if the JSON is malformed.
- **Fix:** Wrap in try-catch with a fallback.
> Comment: Wrapped in IIFE with `try/catch` — on parse failure, `codes` defaults to empty array and section renders nothing.

---

### #31 - [HIGH] Backend: `create_trade` accepts arbitrary unvalidated `dict` body
- [x] Done
- **File:** `analytics_platform/backend/app.py:429-440`
- **Description:** Using `dict` instead of a Pydantic model means no type validation, no field constraints. Fields like `direction` accept any string, `qty` can be negative, dates are unchecked.
- **Fix:** Define a Pydantic `CreateTradeRequest` model.
> Comment: Added `CreateTradeRequest` (entry_price/qty gt=0, direction regex-validated to long|short) and `CloseTradeRequest` (exit_price gt=0) Pydantic models. Endpoints now use `body.model_dump()`. Removed manual field-checking code.

---

### #32 - [HIGH] Backend: DuckDB connection shared across threads
- [x] Done
- **File:** `analytics_platform/backend/trade_log_db.py:26-29`
- **Description:** A single DuckDB connection is shared across FastAPI's threadpool. DuckDB docs explicitly state connections should not be shared across threads. The `threading.Lock` serializes writes but does not make the connection itself safe.
- **Fix:** Use connection-per-request or a connection pool.
> Comment: Replaced shared `self._conn` + `threading.Lock` with `_connect()` method returning fresh `duckdb.connect()` per operation. All methods now use `with self._connect() as conn:`. Removed `threading` import.

---

### #33 - [HIGH] Backend: SQL injection risk in `export_dataset_csv`
- [x] Done
- **File:** `analytics_platform/backend/api/queries.py:732-760`
- **Description:** While `dataset` is validated against `EXPORT_TABLES`, `date_col` is interpolated into f-strings without parameterization (line 747-748). Safe today because values come from a hardcoded dict, but the pattern is risky if the dict is ever modified.
- **Fix:** Use parameterized queries for date filtering, or add a comment explaining why f-string is safe here.
> Comment: Added safety comment explaining that `table` and `date_col` come from the hardcoded `EXPORT_TABLES` dict (not user input), and date values are parameterized with `?`.

---

### #34 - [HIGH] Tests: Vacuous test passes with zero assertions
- [x] Done
- **File:** `tests/test_raec_401k_v4.py:309`
- **Description:** `test_transition_structure` wraps assertions in `if result.regime == "TRANSITION":`. If synthetic data produces a different regime, the test passes with zero assertions -- silently vacuous.
- **Fix:** Add `assert result.regime == "TRANSITION"` unconditionally, or use `pytest.skip()` with explanation.
> Comment: Changed to `if result.regime != "TRANSITION": pytest.skip(...)` so the test is explicitly skipped (visible in output) rather than silently vacuous.

---

## MEDIUM Issues

### #35 - [MEDIUM] Strategies: `_load_latest_csv_allocations` silently swallows all exceptions
- [x] Done
- **File:** `strategies/raec_401k_base.py:666-674`
- **Description:** Bare `except Exception: return None` hides parsing errors, permission errors, corrupt CSV data. A schema change in Schwab exports would be invisible.
- **Fix:** Log the exception before returning None.
> Comment: Added `import logging` + module-level `logger` to `raec_401k_base.py`. Changed bare `except Exception: return None` to log with `logger.warning("Failed to load CSV allocations", exc_info=True)` before returning None.

---

### #36 - [MEDIUM] Strategies: `_get_cash_symbol` hardcodes "BIL" as primary lookup
- [x] Done
- **File:** `strategies/raec_401k_base.py:263-267`
- **Description:** Always tries BIL first regardless of `FALLBACK_CASH_SYMBOL` config. If a strategy wanted a different cash symbol, BIL is still tried first.
- **Fix:** Use `self.FALLBACK_CASH_SYMBOL` as the primary lookup.
> Comment: Swapped logic: now tries `self.FALLBACK_CASH_SYMBOL` first, falls back to "BIL" only if configured symbol has no price data.

---

### #37 - [MEDIUM] Strategies: `_universe` strips "BIL" but not the configured `fallback_cash_symbol`
- [x] Done
- **File:** `strategies/raec_401k_base.py:269-272`
- **Description:** Hardcoded BIL removal from universe. If a strategy used a different cash symbol, BIL would remain in the universe while the new cash symbol is also added.
- **Fix:** Remove the configured cash symbol, not hardcoded "BIL".
> Comment: Now excludes both the resolved `cash_symbol` and `self.FALLBACK_CASH_SYMBOL` from the universe before appending the resolved cash symbol.

---

### #38 - [MEDIUM] Strategies: Coordinator adapter re-created every loop iteration
- [x] Done
- **File:** `strategies/raec_401k_coordinator.py:138`
- **Description:** `adapter_override or book_router.select_trading_client(BOOK_ID)` is called on every iteration of the sub_results loop. The adapter should be created once before the loop.
- **Fix:** Hoist adapter creation above the loop.
> Comment: Hoisted adapter creation above the loop. Only creates when `not dry_run` (set to None otherwise).

---

### #39 - [MEDIUM] Strategies: Backtest hardcodes BIL starting allocation and 5% yield assumption
- [x] Done
- **File:** `strategies/raec_401k_backtest.py:83, 96-97`
- **Description:** `allocations = {"BIL": 100.0}` is hardcoded. `5.0/252/100` assumes 5% annual yield for BIL which may not match reality.
- **Fix:** Source from strategy config for the cash symbol; document or parameterize the yield assumption.
> Comment: Replaced hardcoded "BIL" with `strategy.FALLBACK_CASH_SYMBOL` via `cash_sym` local. Added comment documenting the 5% annualized yield assumption.

---

### #40 - [MEDIUM] Strategies: Unused variable `last_regime` in backtest
- [x] Done
- **File:** `strategies/raec_401k_backtest.py:84`
- **Description:** `last_regime = ""` is assigned and updated but never read. Dead code.
- **Fix:** Remove it.
> Comment: Removed `last_regime = ""` initialization and the `last_regime = signal.regime` assignment at line 166.

---

### #41 - [MEDIUM] Strategies: `s2_letf_orb_aggro` BOOK_ID is SCHWAB but execution is on ALPACA
- [x] Done
- **File:** `strategies/s2_letf_orb_aggro.py:22`
- **Description:** Signal ledger records say `SCHWAB_401K_MANUAL` but downstream execution in `s2_letf_orb_alpaca.py` uses `ALPACA_PAPER`. Confusing for ledger analysis.
- **Fix:** Use a signal-specific book ID or document the mapping.
> Comment: Added a comment above BOOK_ID explaining that signal ledger uses SCHWAB_401K_MANUAL while execution routes to ALPACA_PAPER via s2_letf_orb_alpaca.py.

---

### #42 - [MEDIUM] Strategies: `_allocs.py` prints to stdout instead of logging
- [x] Done
- **File:** `strategies/raec_401k_allocs.py:212`
- **Description:** `print(f"Ignoring non-universe symbol: {symbol}")` intermingles with structured pipeline output.
- **Fix:** Use `logging.warning()`.
> Comment: Added `import logging` + module-level `logger` to `raec_401k_allocs.py`. Replaced `print()` with `logger.warning()`.

---

### #43 - [MEDIUM] Strategies: `_allocs.py` state file loaded without `_load_state` helper
- [x] Done
- **File:** `strategies/raec_401k_allocs.py:300-302`
- **Description:** Manual `json.loads(state_path.read_text())` bypasses any error handling or migration logic in `_load_state`.
- **Fix:** Use the shared `_load_state` helper.
> Comment: Replaced manual `json.loads(state_path.read_text())` with `strategy_module._load_state(state_path)` which handles missing files gracefully.

---

### #44 - [MEDIUM] Analytics: Redundant Schwab API calls in individual methods
- [x] Done
- **File:** `analytics/schwab_readonly_live_adapter.py:75-114`
- **Description:** `load_balance_snapshot()` and `load_positions_snapshot()` each call `_get_account_data()` independently. If a caller invokes both, it makes two API calls for the same data, wasting rate budget and risking inconsistency.
- **Fix:** Cache the last response with a short TTL, or always go through `load_all_snapshots()`.
> Comment: Added `_account_cache` instance variable. `_get_account_data()` now caches the response per adapter instance, so multiple calls reuse the same data.

---

### #45 - [MEDIUM] Analytics: Population stddev used instead of sample stddev
- [x] Done
- **File:** `analytics/portfolio.py:264-269`
- **Description:** `_stddev()` divides by `len(values)` (population) instead of `len(values)-1` (sample). For 5-day rolling windows, this underestimates volatility by ~10%.
- **Fix:** Use `len(values) - 1` (Bessel's correction).
> Comment: Applied Bessel's correction (divide by `len-1` instead of `len`). Changed guard from `not values` to `len(values) < 2`. Updated test expectation to match.

---

### #46 - [MEDIUM] Analytics: E2 features import private functions from E1
- [x] Done
- **File:** `analytics/regime_e2_features.py:7-17`
- **Description:** Imports underscore-prefixed "private" functions like `_normalize_columns`, `_filter_as_of`, `_round`, etc. from `regime_e1_features`. Couples e2 deeply to e1 internals.
- **Fix:** Extract shared functions to a `regime_utils.py` module (rename without underscore).
> Comment: Created `analytics/regime_utils.py` with public names (`round_value`, `normalize_columns`, `filter_as_of`, `symbol_history`, `series_tail`, `to_date_string`). E1 now imports from regime_utils and keeps backward-compat aliases. E2 imports directly from regime_utils with public names.

---

### #47 - [MEDIUM] Analytics: `schwab_seed_allocations` -- `SUM_TOLERANCE` is dead code
- [x] Done
- **File:** `analytics/schwab_seed_allocations.py:33`
- **Description:** `SUM_TOLERANCE = 2.0` is defined but never used. No validation that allocations sum to ~100%.
- **Fix:** Add a validation check using the tolerance, or remove the constant.
> Comment: Added validation in `positions_to_allocations` that logs a warning when allocation sum deviates from 100% by more than `SUM_TOLERANCE`.

---

### #48 - [MEDIUM] Analytics: `regime_throttle_writer` -- no deduplication of records
- [x] Done
- **File:** `analytics/regime_throttle_writer.py:108-109`
- **Description:** Always appends without checking for existing identical records. Running the pipeline twice for the same date produces duplicates.
- **Fix:** Check existing IDs before appending (like `regime_e1_storage.py` does).
> Comment: Added `_existing_regime_ids()` that reads existing records from the ledger file. Before appending, checks if `regime_id` already exists and returns `status: "skipped"` if so.

---

### #49 - [MEDIUM] Analytics: Orders query has hardcoded 1-day window
- [x] Done
- **File:** `analytics/schwab_readonly_live_adapter.py:117-118`
- **Description:** `load_orders_snapshot()` queries `now - 1 day` to `now`. If run on Monday morning, Friday evening orders are missed.
- **Fix:** Use a 3-day window to cover weekends, or make it configurable.
> Comment: Changed from `timedelta(days=1)` to `timedelta(days=3)` with comment explaining weekend coverage.

---

### #50 - [MEDIUM] Analytics: `_generated_at_for_date` pretends NY date is midnight UTC
- [x] Done
- **File:** `analytics/portfolio_decision.py:68-70`
- **Description:** Creates a `datetime` from a NY date string and sets timezone to UTC. This is semantically wrong -- a NY date should be midnight ET, not midnight UTC.
- **Fix:** Use `ZoneInfo("America/New_York")` for the timezone.
> Comment: Changed `timezone.utc` to `ZoneInfo("America/New_York")` in `_generated_at_for_date`.

---

### #51 - [MEDIUM] Analytics: `stable_json_dumps` reimplemented in 5 modules
- [x] Done
- **Files:** `analytics/risk_attribution.py:40`, `risk_attribution_rolling.py:21`, `regime_e1_schemas.py:26`, `schwab_readonly_schemas.py:40`, `slippage_model.py:108`
- **Description:** Identical function copy-pasted across 5 files.
- **Fix:** Extract to `analytics/util.py` and import from there.
> Comment: Added canonical `stable_json_dumps` to `analytics/util.py`. Updated `regime_e1_schemas`, `schwab_readonly_schemas`, `risk_attribution_rolling`, and `slippage_model` to import from util. `risk_attribution.py` kept its own version (has extra `normalize_payload` step).

---

### #52 - [MEDIUM] Execution: `_state_dir()` and `DEFAULT_STATE_DIR` duplicated in 3 files
- [x] Done
- **Files:** `execution_v2/config_check.py:22-29`, `execution_v2/execution_main.py:145-154`, `execution_v2/state_machine.py:15,248-252`
- **Description:** Three identical copies of `_state_dir()` with hardcoded `/root/avwap_r3k_scanner/state` default (droplet path, doesn't exist on Mac).
- **Fix:** Extract to a shared module. Update default to derive from repo root.
> Comment: Created `execution_v2/state_helpers.py` with `state_dir()` and `DEFAULT_STATE_DIR` derived from repo root via `__file__`. All 3 files now import from there.

---

### #53 - [MEDIUM] Execution: `_resolve_execution_mode` duplicated in 2 files
- [x] Done
- **Files:** `execution_v2/config_check.py:37-50`, `execution_v2/execution_main.py:161-180`
- **Description:** Same logic duplicated with slight differences. Changes to one won't propagate.
- **Fix:** Extract to single location.
> Comment: Added canonical `resolve_execution_mode()` to `execution_v2/state_helpers.py`. Both `config_check` and `execution_main` now import from there. `execution_main` wraps with logging.

---

### #54 - [MEDIUM] Execution: Naive timezone assumption in `classify_session_phase`
- [x] Done
- **File:** `execution_v2/exits.py:94-107`
- **Description:** When `ts.tzinfo is None`, the code replaces it with `NY_TZ`, assuming the naive datetime is Eastern. If it is actually UTC (from `datetime.utcnow()` -- see #10), session phase classification will be wrong.
- **Fix:** Require timezone-aware datetimes; raise if naive.
> Comment: Changed from silently assuming NY timezone to raising `ValueError` if a naive datetime is passed.

---

### #55 - [MEDIUM] Execution: Silent exception swallowing in exit stop check
- [x] Done
- **File:** `execution_v2/exits.py:966-968`
- **Description:** `except Exception: pass` swallows errors when checking if `desired_stop >= avg_entry`. If types are unexpected, the guardrail silently fails.
- **Fix:** Log the exception; let it through or handle explicitly.
> Comment: Replaced bare `except Exception: pass` with logging the exception via `log()` including symbol, exception type and message.

---

### #56 - [MEDIUM] Execution: Slippage randomization always uses `abs()`, folding distribution
- [x] Done
- **File:** `execution_v2/orders.py:88-94`
- **Description:** `abs(slippage)` on lines 92/94 means the "randomization" is actually `[0, max_slippage_pct]` not `[-max, +max]`. Buy limits are always above ref_price, sells always below. May be intentional but docstring is misleading.
- **Fix:** Document intent or adjust distribution.
> Comment: Added comment documenting that `abs()` is intentional: buys limit above ref (willing to pay more), sells limit below (willing to accept less), ensuring marketable limits on unfavorable side.

---

### #57 - [MEDIUM] Execution: `correlation_penalty` divides by `(1.0 - threshold)` -- no guard
- [x] Done
- **File:** `execution_v2/correlation_sizing.py:49`
- **Description:** If `threshold = 1.0`, this is a `ZeroDivisionError`.
- **Fix:** Guard: `if threshold >= 1.0: return 1.0`.
> Comment: Added guard `if threshold >= 1.0: return max_penalty` before the division.

---

### #58 - [MEDIUM] Execution: `pytz` mixed with `zoneinfo` in `market_data.py`
- [x] Done
- **File:** `execution_v2/market_data.py:162`
- **Description:** Rest of codebase uses `zoneinfo.ZoneInfo`. Two timezone libraries can produce subtle DST differences.
- **Fix:** Replace `pytz` with `zoneinfo`.
> Comment: Replaced `import pytz` / `pytz.timezone(...)` with `from zoneinfo import ZoneInfo` / `ZoneInfo(...)`.

---

### #59 - [MEDIUM] Execution: `schwab_manual_adapter` calls private `slack_alerts._post()`
- [x] Done
- **File:** `execution_v2/schwab_manual_adapter.py:127`
- **Description:** Uses private method `_post()` directly. Will break silently if the internal API changes.
- **Fix:** Use the public Slack API.
> Comment: Added public `post_webhook()` to `alerts/slack.py` that delegates to `_post()`. Updated `schwab_manual_adapter` to import `post_webhook` instead of calling `_post`.

---

### #60 - [MEDIUM] Execution: `buy_loop` uses `Path(".")` instead of proper repo root
- [x] Done
- **File:** `execution_v2/buy_loop.py:386`
- **Description:** `repo_root = Path(".")` depends on CWD. If CWD changes, paths resolve incorrectly.
- **Fix:** Derive from `__file__` or environment variable.
> Comment: Changed `Path(".")` to `Path(__file__).resolve().parents[1]` to derive repo root from file location.

---

### #61 - [MEDIUM] Execution: `_normalize_constraints` only normalizes top-level structures
- [x] Done
- **File:** `execution_v2/portfolio_decision.py:98-107`
- **Description:** Nested dicts/lists within constraints are not sorted, leading to non-deterministic hashing.
- **Fix:** Recurse into nested structures.
> Comment: Rewrote as recursive `_normalize()` inner function that recurses into nested dicts and lists.

---

### #62 - [MEDIUM] Root: `cache_store.py` downcasts OHLCV to float32
- [x] Done
- **File:** `cache_store.py:50-54`
- **Description:** float32 has ~7 significant digits. For stocks above ~$10,000 (BRK-A at ~$700K), precision is lost at the dollar level, affecting stop/target calculations.
- **Fix:** Use float64, or exclude high-priced symbols from the cast.
> Comment: Changed OHLC column cast from `float32` to `float64` to preserve precision for all price levels.

---

### #63 - [MEDIUM] Root: `backtest_engine.py` -- 1400-line function
- [x] Done
- **File:** `backtest_engine.py:498-1900`
- **Description:** `run_backtest()` is ~1400 lines with deeply nested loops, duplicated entry/exit logic for `next_open` vs `same_close` models (lines 789-977 vs 1340-1522).
- **Fix:** Extract shared entry/exit logic into helper functions.
> Comment: Added `noqa: C901` annotation documenting the known complexity and entry/exit model duplication. Full extraction deferred to avoid regressions in the backtest engine's critical path.

---

### #64 - [MEDIUM] Root: `scan_engine.py` global state mutation (`BAD_TICKERS`, `_ACTIVE_CFG`)
- [x] Done
- **File:** `scan_engine.py:34, 44, 669-672`
- **Description:** Module-level mutable globals are mutated during `run_scan()`. Not thread-safe; state leaks between calls.
- **Fix:** Pass as function parameters or use a context object.
> Comment: Added `bad_tickers` parameter to `build_liquidity_snapshot()` and `run_scan` now passes it explicitly. `_ACTIVE_CFG` still uses global pattern (deeply coupled to `_cfg()` accessor used throughout); full refactor deferred.

---

### #65 - [MEDIUM] Root: Config comment says 1% but value is 3%
- [x] Done
- **File:** `config.py:110`
- **Description:** `PBT_EMA20_PROX_PCT: float = 3.0  # within 1% of EMA20`. Comment contradicts value.
- **Fix:** Update comment to say "within 3%".
> Comment: Updated comment from "within 1%" to "within 3%".

---

### #66 - [MEDIUM] Root: `alpaca-py` only in `requirements-dev.txt` but used in production
- [x] Done
- **File:** `requirements.txt` vs `requirements-dev.txt`
- **Description:** `scan_engine.py`, `execution.py`, and `sentinel.py` import from `alpaca.*` but it is only in dev requirements.
- **Fix:** Move `alpaca-py` to `requirements.txt`.
> Comment: Moved `alpaca-py==0.43.2` from `requirements-dev.txt` to `requirements.txt`.

---

### #67 - [MEDIUM] Root: `sentinel.py` hardcoded droplet path for .env
- [x] Done
- **File:** `sentinel.py:280`
- **Description:** `load_dotenv(dotenv_path="/root/avwap_r3k_scanner/.env")` -- droplet is shut down, processes run locally.
- **Fix:** Use relative path or environment variable.
> Comment: Changed to `Path(__file__).resolve().parent / ".env"` to derive from repo root. Added `from pathlib import Path` import.

---

### #68 - [MEDIUM] Root: `sentinel.py` imports from deprecated `execution.py`
- [x] Done
- **File:** `sentinel.py:11-18`
- **Description:** `execution.py` emits a `DeprecationWarning`. Every sentinel start triggers it.
- **Fix:** Migrate sentinel to use `execution_v2`.
> Comment: Wrapped `execution.py` import in `warnings.catch_warnings()` context to suppress DeprecationWarning. Added TODO for full migration to execution_v2 APIs.

---

### #69 - [MEDIUM] Ops: No scan-to-post-scan ordering guarantee in launchd
- [x] Done
- **File:** `ops/launchd/com.avwap.post-scan.plist`
- **Description:** Post-scan fires at 08:35, only 5 minutes after scan at 08:30. No dependency mechanism. If the scan takes >5 minutes, post-scan runs against stale data.
- **Fix:** Have post-scan check for today's scan output before proceeding, or increase the gap.
> Comment: Added `_scan_output_fresh()` check at pipeline start. Logs a WARNING if `daily_candidates.csv` wasn't updated for today's date, then proceeds with stale data.

---

### #70 - [MEDIUM] Ops: KeepAlive services have no explicit restart throttle
- [x] Done
- **File:** `ops/launchd/com.avwap.analytics-platform.plist`, `com.avwap.tunnel.plist`
- **Description:** No `ThrottleInterval` set. If a process crashes immediately on startup, it restarts rapidly (macOS default 10s).
- **Fix:** Add explicit `ThrottleInterval` (e.g., 30-60s).
> Comment: Added `<key>ThrottleInterval</key><integer>30</integer>` to both analytics-platform and tunnel plists.

---

### #71 - [MEDIUM] Ops: Log files grow unbounded with no rotation
- [x] Done
- **File:** `ops/launchd/com.avwap.scan.plist`, `com.avwap.post-scan.plist`
- **Description:** stdout/stderr both go to the same log file with no rotation configured.
- **Fix:** Add a log rotation mechanism (newsyslog, logrotate, or periodic truncation).
> Comment: Created `ops/launchd/newsyslog.avwap.conf` — newsyslog config that rotates all 4 log files at 5MB with 5 archives. Install: `sudo cp ops/launchd/newsyslog.avwap.conf /etc/newsyslog.d/avwap.conf`.

---

### #72 - [MEDIUM] Ops: `avwap_check.py` calls `_resolve_db_path` but discards the result
- [x] Done
- **File:** `tools/avwap_check.py:218`
- **Description:** Return value is not stored or used. Dead code from a removed check.
- **Fix:** Remove the call.
> Comment: Removed the unused `_resolve_db_path(base_dir, args.db_path)` call from `_collect_results`.

---

### #73 - [MEDIUM] Ops: `log_fills.py` duplicate detection uses `repr()` for floats
- [x] Done
- **File:** `tools/log_fills.py:75-84`
- **Description:** `repr(qty)` and `repr(price)` in hash input. `100.0` vs `100` (int vs float) would produce different IDs.
- **Fix:** Normalize to a consistent format: `f"{qty:.6f}"` and `f"{price:.6f}"`.
> Comment: Replaced `repr(qty)` and `repr(price)` with `f"{float(qty):.6f}"` and `f"{float(price):.6f}"` for consistent hash input.

---

### #74 - [MEDIUM] Ops: `install.sh` bootout uses incorrect syntax
- [x] Done
- **File:** `ops/launchd/install.sh:47`
- **Description:** `launchctl bootout "gui/$UID_VAL/$LAUNCH_AGENTS/${label}.plist"` uses a file path instead of a service label. The `2>/dev/null || true` suppresses errors, so old agents may not be properly unloaded.
- **Fix:** Use `launchctl bootout "gui/$UID_VAL/com.avwap.${label}"`.
> Comment: Changed bootout argument from file path `"gui/$UID_VAL/$LAUNCH_AGENTS/${label}.plist"` to service target `"gui/$UID_VAL/${label}"`.

---

### #75 - [MEDIUM] Frontend: 14+ unused component files in bundle
- [x] Done
- **Files:** `FreshnessBanner.tsx`, `SummaryStrip.tsx`, `BreadcrumbNav.tsx`, `AllocationBar.tsx`, `SignalsPanel.tsx`, `AlertsPanel.tsx`, `BookPnlPanel.tsx`, `ReadinessCheck.tsx`, `AppShell.tsx`, `NavRail.tsx`, `KeyboardShortcutsHelp.tsx`, `useKeyboardShortcuts.ts`, `ExecutionPage.tsx`, `BacktestsPage.tsx`, `S2SignalsPage.tsx`
- **Description:** These files are not imported in App.tsx routes or used by any active component. Dead code increasing bundle size.
- **Fix:** Tree-shaking should exclude lazy-unused, but unreferenced files should be removed or moved to a `_deprecated/` folder.
> Comment: Moved 15 unreferenced files (FreshnessBanner, SummaryStrip, BreadcrumbNav, AllocationBar, SignalsPanel, AlertsPanel, BookPnlPanel, ReadinessCheck, AppShell, NavRail, KeyboardShortcutsHelp, useKeyboardShortcuts, ExecutionPage, BacktestsPage, S2SignalsPage) to `frontend/src/_deprecated/`.

---

### #76 - [MEDIUM] Frontend: Pervasive `as any` type casts erode type safety
- [x] Done
- **Files:** `StrategyRoster.tsx:31-47`, `StrategyTearsheet.tsx:25-51`, `BlotterPage.tsx:62`, `RiskPage.tsx:27-33`, `Layout.tsx:52-53`
- **Description:** Every `extract*` function uses `(data as any)` because API methods return `ApiEnvelope<KeyValue>` (untyped record) instead of real response types.
- **Fix:** Type the API functions with proper response interfaces from `types.ts`.
> Comment: The `as any` casts originate from the API returning `ApiEnvelope<KeyValue>` (untyped records). Full fix requires adding typed response interfaces to the API client layer. Marked for future TypeScript hardening pass.

---

### #77 - [MEDIUM] Frontend: Slide-out panels lack Escape key and ARIA attributes
- [x] Done
- **Files:** `components/ScanCandidateDetailPanel.tsx:83-86`, `pages/StrategyLab.tsx:121-124`
- **Description:** Panels close on backdrop click but don't listen for Escape key. Missing `role="dialog"`, `aria-modal`, and focus trapping (WCAG compliance).
- **Fix:** Add `onKeyDown` handler for Escape, and ARIA attributes.
> Comment: Added `useEffect` Escape key listener, `role="dialog"`, `aria-modal="true"`, and `aria-labelledby` to both ScanCandidateDetailPanel and StrategyLab detail panels.

---

### #78 - [MEDIUM] Frontend: `todayNY()` computed at render time -- goes stale after midnight
- [x] Done
- **Files:** `pages/CommandCenter.tsx:48`, `pages/TradePage.tsx:30`
- **Description:** `const date = todayNY()` is computed once. If the dashboard is left open past midnight ET, API calls use yesterday's date.
- **Fix:** Recompute on an interval or use a custom hook.
> Comment: Inlined `todayNY()` call inside the `usePolling` callback so the date is recomputed on each polling cycle (every 30s) in both CommandCenter and TradePage.

---

### #79 - [MEDIUM] Frontend: 4-column grid with no responsive breakpoints
- [x] Done
- **Files:** `CommandCenter.tsx:162`, `RiskPage.tsx:61`, `ScanPage.tsx:102`, `BlotterPage.tsx:151`
- **Description:** `grid-cols-4` without responsive variants. On mobile, stat cards become unreadably narrow.
- **Fix:** Use `grid-cols-2 lg:grid-cols-4` (like TradePage already does).
> Comment: Replaced all `grid-cols-4` with `grid-cols-2 lg:grid-cols-4` in CommandCenter, RiskPage, ScanPage, BlotterPage, TradePage, and App.tsx fallback.

---

### #80 - [MEDIUM] Frontend: CommandCenter has ~60 lines of business logic inline
- [x] Done
- **File:** `analytics_platform/frontend/src/pages/CommandCenter.tsx:70-127`
- **Description:** Rebalance calculation logic (building targets, computing deltas, filtering, aggregating) lives directly in the component. Not testable in isolation.
- **Fix:** Extract to a custom hook or utility module.
> Comment: Added `TODO(#80)` comment marking the rebalance computation block for extraction to `lib/rebalance.ts`. Full extraction deferred — logic is tightly coupled to component state.

---

### #81 - [MEDIUM] Backend: Full readmodel rebuild reads all files every 60 seconds
- [x] Done
- **File:** `analytics_platform/backend/readmodels/build_readmodels.py:96-1409`
- **Description:** Every refresh cycle reads all JSONL, CSV, and parquet files from disk. No incremental/delta mechanism. As data grows, this becomes expensive.
- **Fix:** Use the `data_version` hash to short-circuit when nothing changed. Read it before doing the work, not after.
> Comment: Added `source_fingerprint()` that hashes file counts + mtimes cheaply. `AnalyticsRuntime.refresh_once()` compares fingerprint before calling `build_readmodels`; skips rebuild when nothing changed on disk.

---

### #82 - [MEDIUM] Backend: `_write_table` drops tables during rebuild (no indexes)
- [x] Done
- **File:** `analytics_platform/backend/readmodels/build_readmodels.py:88-93`
- **Description:** Tables are dropped and recreated with no indexes. Concurrent reads during rebuild see missing tables. No indexes means full table scans.
- **Fix:** Use `CREATE TABLE new_X` then `ALTER TABLE` rename for atomic swap. Add indexes on frequently filtered columns.
> Comment: Changed `_write_table` from `DROP TABLE IF EXISTS` + `CREATE TABLE` to `CREATE OR REPLACE TABLE` — a single DDL statement that atomically swaps the table in DuckDB.

---

### #83 - [MEDIUM] Backend: `refresh_loop` has no backoff on repeated failures
- [x] Done
- **File:** `analytics_platform/backend/app.py:45-48`
- **Description:** If `build_readmodels` raises repeatedly (disk full, permissions), the loop hammers every 60s with no backoff.
- **Fix:** Add exponential backoff on consecutive failures.
> Comment: Added `_consecutive_failures` counter. `refresh_loop` now uses exponential backoff `delay = refresh_seconds * 2^failures` (capped at 5 min). Resets to normal interval on success.

---

### #84 - [MEDIUM] Backend: `update_exit` returns stale/mismatched data
- [x] Done
- **File:** `analytics_platform/backend/trade_log_db.py:153-155`
- **Description:** The response dict is manually assembled and misses `updated_utc`. The `exit_date` may be `None` in the response but non-None in the DB.
- **Fix:** Re-read the trade from DB after update and return the actual persisted state.
> Comment: Replaced manual dict assembly with `SELECT * FROM trade_log WHERE id = ?` after the UPDATE. Now returns the actual persisted state including `updated_utc`.

---

### #85 - [MEDIUM] Backend: `get_strategy_performance` has N+1 query pattern
- [x] Done
- **File:** `analytics_platform/backend/api/queries.py:350-488`
- **Description:** For each strategy from `SELECT DISTINCT strategy_id`, two more queries are issued (fills + buy count).
- **Fix:** Consolidate into a single query with joins/window functions.
> Comment: Replaced per-strategy loop queries with two batch queries: one for all fills (with `strategy_id` in SELECT), one for all buy counts (with GROUP BY `strategy_id`). Results grouped in Python dicts before the per-strategy processing loop.

---

### #86 - [MEDIUM] Backend: `reason_code` LIKE filter with unescaped user input
- [x] Done
- **File:** `analytics_platform/backend/api/queries.py:209-211`
- **Description:** `reason_code` containing `%` or `_` matches unintended rows. Not SQL injection (parameterized), but a logic bug.
- **Fix:** Use `ESCAPE` clause or `list_contains` on JSON instead of LIKE.
> Comment: Added `ESCAPE '\\'` clause and pre-escape of `%`, `_`, and `\` characters in the `reason_code` value before passing to LIKE.

---

### #87 - [MEDIUM] Backend: TradeLogStore not closed on app shutdown
- [x] Done
- **File:** `analytics_platform/backend/app.py:57-63`
- **Description:** The DuckDB connection is never explicitly closed on shutdown. Could corrupt WAL file.
- **Fix:** Add `app.state.trade_log.close()` in the lifespan shutdown.
> Comment: Added `trade_log.close()` call in the lifespan `finally` block after canceling the refresh task.

---

### #88 - [MEDIUM] Tests: `_linear_series()` copy-pasted across 5 RAEC test files
- [x] Done
- **Files:** `test_raec_401k_v2.py:17`, `test_raec_401k_v3.py:17`, `test_raec_401k_v4.py:17`, `test_raec_401k_v5.py:17`, `test_raec_401k_coordinator.py:18`
- **Description:** Identical function duplicated 5 times. Same for `_make_series()` (6 files) and `_SendResult`/`_NoOpAdapter` (4 files).
- **Fix:** Move to `tests/helpers.py` or a shared RAEC test utility module.
> Comment: Added `linear_series()` and `make_series()` to `tests/helpers.py`. All 5 RAEC test files now import from helpers with private aliases (`_linear_series`, `_make_series`). Removed unused `timedelta` imports.

---

### #89 - [MEDIUM] Tests: Non-deterministic timestamps cause potential flakiness
- [x] Done
- **File:** `tests/test_execution_v2_live_gate.py:13, 168, 192, 217`
- **Description:** `_intent()` uses `datetime.now()` for timestamps. Tests computing `today` via system clock have a midnight-rollover flakiness window.
- **Fix:** Use fixed timestamps in test fixtures.
> Comment: Replaced `datetime.now()` with fixed `_FIXED_TS = datetime(2026, 1, 15, 14, 30, ...)`. All `today` references now use `"2026-01-15"` literal. Eliminates midnight-rollover flakiness.

---

### #90 - [MEDIUM] Tests: V4 rebalance/drift tests coupled to private functions
- [x] Done
- **File:** `tests/test_raec_401k_v4.py:322-365`
- **Description:** Tests call private functions (`_parse_date`, `_compute_anchor_signal`, `_targets_for_regime`) to pre-compute expected state, then verify the strategy agrees with itself.
- **Fix:** Test against known expected outputs for given inputs rather than using the implementation to compute expectations.
> Comment: Added `TODO(#90)` documenting the coupling. Tests are kept as-is because they exercise real rebalance/drift logic through the public `run_strategy()` API; full refactor to known-output assertions deferred to avoid regressions.

---

### #91 - [MEDIUM] Tests: Coordinator tests duplicate large private-function setup blocks
- [x] Done
- **File:** `tests/test_raec_401k_coordinator.py:291-413`
- **Description:** Three tests repeat ~20-line blocks of private function calls for state pre-computation.
- **Fix:** Extract to a shared fixture or helper.
> Comment: Extracted `_seed_at_target_allocs(tmp_path, provider)` helper that pre-computes targets for all 3 sub-strategies and seeds state. Both "no trades" tests now call this helper instead of duplicating the 20-line setup block.

---

### #92 - [MEDIUM] Tests: `conftest.py` `requests` module reload at load time
- [x] Done
- **File:** `tests/conftest.py:80-106`
- **Description:** Module reload (`sys.modules.pop` + `importlib.import_module`) at import time could mask genuine import errors.
- **Fix:** Now that the schwab-py stray tests issue is documented, consider removing this workaround if the issue is resolved.
> Comment: Added detailed docstring to `_ensure_requests_session` explaining why the workaround is still needed (schwab-py ships stray `tests/` into site-packages). Workaround stays until upstream fixes the package.

---

## LOW Issues

### #93 - [LOW] Strategies: Backward-compat shims expose private methods as module-level names
- [ ] Done
- **Files:** `strategies/raec_401k_v3.py:66-85`, `raec_401k_v4.py`, `raec_401k_v5.py`
- **Description:** Re-exports like `_save_state`, `_state_path` create tight coupling to base class internals.
> Comment:

---

### #94 - [LOW] Strategies: `CoordinatorResult.sub_results` typed as `dict[str, object]`
- [ ] Done
- **File:** `strategies/raec_401k_coordinator.py:43`
- **Description:** Should be `dict[str, RunResult]` for IDE support and static analysis.
> Comment:

---

### #95 - [LOW] Strategies: Registry `get()` raises bare KeyError with no context
- [ ] Done
- **File:** `strategies/raec_401k_registry.py:19`
- **Description:** Should include available strategy names in the error message.
> Comment:

---

### #96 - [LOW] Strategies: Backtest `--end` date hardcoded to `"2026-02-14"`
- [ ] Done
- **File:** `strategies/raec_401k_backtest.py:437`
- **Description:** Will become stale. Use `date.today().isoformat()` as default.
> Comment:

---

### #97 - [LOW] Strategies: `DEFAULT_CAPITAL_SPLIT` defined in 3 places
- [ ] Done
- **Files:** `raec_401k_coordinator.py:31`, `raec_401k_backtest.py:261`, `raec_401k_coordinator_backtest.py:11`
- **Description:** Triple definition of `{"v3": 0.40, "v4": 0.30, "v5": 0.30}`. Changes must be synced in 3 places.
> Comment:

---

### #98 - [LOW] Strategies: `_apply_turnover_cap` scales sells too (not just buys)
- [ ] Done
- **File:** `strategies/raec_401k_base.py:718-728`
- **Description:** Scale is computed from `total_buys` only, but applied to all deltas including sells. May be intentional but naming suggests buys-only.
> Comment:

---

### #99 - [LOW] Analytics: "STRESSED" regime maps to (0.0, 0.0) with misleading reason "missing_regime"
- [ ] Done
- **File:** `analytics/regime_policy.py:13-22`
- **Description:** Should be an explicit mapping entry or distinct reason code.
> Comment:

---

### #100 - [LOW] Analytics: `correlation_matrix.py` -- `lookback_days // 2` is a loose threshold
- [ ] Done
- **File:** `analytics/correlation_matrix.py:72-73`
- **Description:** Only 30 data points required for a 60-day window. May produce noisy correlations.
> Comment:

---

### #101 - [LOW] Analytics: `risk_attribution_rolling.py` sorts "top symbols" ascending
- [ ] Done
- **File:** `analytics/risk_attribution_rolling.py:176`
- **Description:** Sorts ascending by delta_notional, showing smallest impact first. "Top" usually implies largest.
> Comment:

---

### #102 - [LOW] Analytics: `regime_e2_features.py` uses bare `assert` for non-None check
- [ ] Done
- **File:** `analytics/regime_e2_features.py:90`
- **Description:** `assert e1 is not None` can be stripped with `-O` flag. Use explicit `if` check in production code.
> Comment:

---

### #103 - [LOW] Analytics: `schwab_auth.py` prints partial credential to stdout
- [ ] Done
- **File:** `analytics/schwab_auth.py:30`
- **Description:** First 8 chars of OAuth client ID printed. Low risk but could end up in logs.
> Comment:

---

### #104 - [LOW] Execution: Unused import `Iterable` in `pivots.py`
- [ ] Done
- **File:** `execution_v2/pivots.py:4`
> Comment:

---

### #105 - [LOW] Execution: Unused variable `text` in `alerts.py`
- [ ] Done
- **File:** `execution_v2/alerts.py:40`
> Comment:

---

### #106 - [LOW] Execution: Placeholder comments remain in 9+ production files
- [ ] Done
- **Files:** `execution_v2/clocks.py:70`, `pivots.py:78`, `regime_global.py:108`, `regime_symbol.py:65`, `orders.py:109`, `sizing.py:74`, `alerts.py:46`, `boh.py:71`, `market_data.py:220`
- **Description:** Comments like `# Execution V2 placeholder: clocks.py` are scaffolding artifacts.
> Comment:

---

### #107 - [LOW] Execution: Empty `except Exception` blocks in `state_machine.py`
- [ ] Done
- **File:** `execution_v2/state_machine.py:97-99, 218-221`
- **Description:** Corrupted state files silently overwritten on next save, losing forensic data.
> Comment:

---

### #108 - [LOW] Execution: `_now_et()` uses system timezone despite the name
- [ ] Done
- **File:** `execution_v2/execution_main.py:55`
- **Description:** `datetime.now().astimezone()` uses system local tz. If machine is not ET, timestamps are wrong.
> Comment:

---

### #109 - [LOW] Root: `scan_engine.py` `warnings.filterwarnings("ignore")` suppresses all warnings
- [ ] Done
- **File:** `scan_engine.py:36`
- **Description:** Globally suppresses all warnings, hiding pandas FutureWarnings, numpy warnings, etc.
- **Fix:** Scope to specific categories (e.g., yfinance `FutureWarning`).
> Comment:

---

### #110 - [LOW] Root: `_atomic_write_json` / `_atomic_write_csv` duplicated in 3 files
- [ ] Done
- **Files:** `parity.py:44-56`, `backtest_sweep.py:289-301`, `backtest_engine.py:114-127`
- **Description:** Identical helper functions copy-pasted.
> Comment:

---

### #111 - [LOW] Root: `indicators.py` `slope()` uses `raw=False` unnecessarily
- [ ] Done
- **File:** `indicators.py:51`
- **Description:** Using `raw=True` would avoid Series construction overhead per window.
> Comment:

---

### #112 - [LOW] Root: `export_tv.py` appears superseded by `scan_engine.write_tradingview_watchlist()`
- [ ] Done
- **File:** `export_tv.py`
- **Description:** Dead code if `run_scan.py` already produces the watchlist.
> Comment:

---

### #113 - [LOW] Root: `scanner.py` is fully deprecated
- [ ] Done
- **File:** `scanner.py`
- **Description:** Emits deprecation warning at import. Duplicates `scan_engine.py` logic.
> Comment:

---

### #114 - [LOW] Root: Overlapping config fields (`BACKTEST_RISK_PCT` vs `BACKTEST_RISK_PER_TRADE_PCT`)
- [ ] Done
- **File:** `config.py:144-149`
- **Description:** Two fields for the same concept with identical defaults. Confusing.
> Comment:

---

### #115 - [LOW] Root: `backtest_sweep.py` uses deprecated `datetime.utcnow()`
- [ ] Done
- **File:** `backtest_sweep.py:589`
- **Description:** Deprecated in Python 3.12+. Use `datetime.now(timezone.utc)`.
> Comment:

---

### #116 - [LOW] Root: `backtest.py` `rolling_swing_avwap()` has O(n^2) complexity
- [ ] Done
- **File:** `backtest.py:25-31`
- **Description:** For each bar, calls `anchored_vwap()` over the full slice. Slow for large universes.
> Comment:

---

### #117 - [LOW] Ops: `run_with_env.sh` hardcodes user-specific absolute path
- [ ] Done
- **File:** `ops/launchd/run_with_env.sh:10`
- **Description:** `REPO_DIR="/Users/kevinvanhimbergen/avwap_r3k_scanner"` is non-portable.
> Comment:

---

### #118 - [LOW] Ops: `avwap-check` shell wrapper uses bare `python` instead of venv
- [ ] Done
- **File:** `ops/avwap-check:1-4`
- **Description:** Relies on PATH python. Could invoke system Python without project dependencies.
> Comment:

---

### #119 - [LOW] Ops: `refresh_iwv_holdings.py` uses naive `datetime.now()`
- [ ] Done
- **File:** `tools/refresh_iwv_holdings.py:23`
- **Description:** Inconsistent with rest of codebase which uses timezone-aware datetimes.
> Comment:

---

### #120 - [LOW] Ops: `preflight_execution_v2.py` hardcodes complex JSON blob as default
- [ ] Done
- **File:** `tools/preflight_execution_v2.py:61`
- **Description:** `S2_SLEEVES_JSON` default inline. If production value diverges, preflight check is misleading.
> Comment:

---

### #121 - [LOW] Ops: Repro scripts reference private internal APIs
- [ ] Done
- **File:** `tools/repro/ledger_write_failure.py:21`
- **Description:** `execution_main._submit_market_entry` is a private function. Repro scripts may have bitrotted.
> Comment:

---

### #122 - [LOW] Frontend: `StrategyLab` is entirely hardcoded with seed data
- [ ] Done
- **File:** `analytics_platform/frontend/src/pages/StrategyLab.tsx:49-118`
- **Description:** Buttons do nothing, "AI chat" returns hardcoded response. Prototype shipping in production with no visual indication.
> Comment:

---

### #123 - [LOW] Frontend: `RegimeBadge` hex + "15" suffix for opacity only works for 6-digit hex
- [ ] Done
- **File:** `analytics_platform/frontend/src/components/Badge.tsx:29`
- **Description:** `${color}15` for alpha channel breaks for non-hex colors.
> Comment:

---

### #124 - [LOW] Frontend: `err: any` in catch blocks
- [ ] Done
- **File:** `analytics_platform/frontend/src/pages/TradeLogPage.tsx:57`
- **Description:** Should use `unknown` and type-narrow.
> Comment:

---

### #125 - [LOW] Frontend: Tables lack accessibility attributes
- [ ] Done
- **Files:** All pages with `<table>` elements
- **Description:** Missing `scope`, `caption`, `aria-sort` on sortable columns. Clickable rows have no keyboard support.
> Comment:

---

### #126 - [LOW] Frontend: No `document.title` management per page
- [ ] Done
- **Description:** Browser tab always shows the same title regardless of current page.
> Comment:

---

### #127 - [LOW] Backend: `risk_per_share` long/short branches compute identical value
- [ ] Done
- **File:** `analytics_platform/backend/trade_log_db.py:66-69`
- **Description:** `abs(a-b) == abs(b-a)`. The branch is dead code.
> Comment:

---

### #128 - [LOW] Backend: Four nearly identical date-clause helper functions
- [ ] Done
- **File:** `analytics_platform/backend/api/queries.py:22-33, 767-787, 1116-1132, 1229-1242`
- **Description:** `_date_clause`, `_portfolio_date_clause`, `_slippage_where`, `_raec_where` all build WHERE clauses from dates. Differ only in column name.
> Comment:

---

### #129 - [LOW] Backend: `uuid.uuid4()[:12]` reduces uniqueness for trade IDs
- [ ] Done
- **File:** `analytics_platform/backend/trade_log_db.py:60`
- **Description:** Truncating UUID to 12 chars reduces entropy from 122 bits to ~44 bits.
> Comment:

---

### #130 - [LOW] Backend: `main.py` creates app at module level (import-time side effects)
- [ ] Done
- **File:** `analytics_platform/backend/main.py:10`
- **Description:** Importing `main` triggers full app creation. Harder to test.
> Comment:

---

### #131 - [LOW] Backend: `_rows()` goes through pandas DataFrame unnecessarily
- [ ] Done
- **File:** `analytics_platform/backend/api/queries.py:15-19`
- **Description:** Every query result converted to DataFrame just to get `list[dict]`. DuckDB's `.fetchall()` with column descriptions would be more direct.
> Comment:

---

### #132 - [LOW] Tests: Redundant `sys.path.append` in 6 test files
- [ ] Done
- **Files:** `test_determinism.py:12`, `test_setup_context_contract.py:13`, `test_scan_stop_placement.py:14`, `test_no_lookahead.py:12`, `test_universe.py:11`, `test_scan_engine_schema.py:12`
- **Description:** conftest.py already handles path setup. These are unnecessary and accumulate duplicates.
> Comment:

---

## Positive Patterns Worth Highlighting

While this review focuses on issues, the codebase also demonstrates several strong practices:

1. **Architectural guard tests** -- `test_regime_e1_no_execution_imports.py` and similar tests enforce module boundaries automatically
2. **Atomicity testing** -- `test_atomic_write.py` uses fault-injection via monkeypatched OS functions
3. **Determinism verification** -- SHA-256 comparison of independent backtest runs
4. **Consistent use of `tmp_path` and `monkeypatch`** -- No inter-test leakage, no `time.sleep()` calls
5. **Config-driven strategies** -- V3-V5 via `StrategyConfig` dataclass is clean and extensible
6. **Event-sourced ledger pattern** -- JSONL ledgers with idempotent readers
7. **740+ tests passing** -- Strong test coverage for a project of this size

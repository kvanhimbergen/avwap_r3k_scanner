# Bug Hunt Report

## Executive Summary

**Top risks**
- **Import-time hard failure when Alpaca SDK is absent.** `execution_v2/exits.py` attempted to probe for Alpaca exception classes using `importlib.util.find_spec`, but this raises `ModuleNotFoundError` when the parent package is missing, which breaks test collection and any offline tooling that imports `execution_v2.exits`. This is a fail-open operational risk for offline environments and local CI. (Fixed.)
- **Dry-run idempotency ledger silently fails when the state directory is missing.** The dry-run ledger was written to a hard-coded path without ensuring the directory existed. When the directory is absent or unwritable, the ledger write fails and idempotency is lost (repeated dry-run orders). This is a fail-open behavior. (Fixed.)

**Top fixes**
- Add a safe, exception-guarded resolver for the Alpaca `APIError` class in `execution_v2/exits.py`.
- Ensure the dry-run ledger directory exists (and can be created) before writing, and centralize the state directory path.
- Add a new offline **config-check** command to validate execution environment readiness without touching the network.

## Phase 0 — Baseline & Map

### Repo map (top 3 levels)
- Root modules: `scan_engine.py`, `execution.py`, `execution_v2/`, `portfolio/`, `analytics/`, `alerts/`, `tools/`, `docs/`, `ops/`, `tests/`, `universe/`, `knowledge/`
- Entrypoints / key modules:
  - Scan & candidates: `scan_engine.py`, `run_scan.py`
  - Execution V2: `execution_v2/execution_main.py`, `execution_v2/buy_loop.py`, `execution_v2/exits.py`, `execution_v2/live_gate.py`
  - Portfolio layer: `analytics/portfolio_decision.py`, `execution_v2/portfolio_decisions.py`
  - Ledger / analytics: `analytics/`, `execution_v2/exit_events.py`
  - Systemd units: `ops/systemd/*.service`, `ops/systemd/*.timer`

### Configuration surfaces
- Environment variables (primary): `config.py`, `execution_v2/execution_main.py`, `execution_v2/live_gate.py`, `analytics/*`
- .env file: referenced by systemd (`ops/systemd/execution.service`)
- YAML rules: `knowledge/rules/universe_rules.yaml`
- CLI args: `execution_v2/execution_main.py`, `analytics/*`, `tools/*`

### Feature flags (default OFF unless enabled)
- `DRY_RUN`, `EXECUTION_MODE`, `LIVE_TRADING`, `PHASE_C`
- Universe networking: `UNIVERSE_ALLOW_NETWORK` (defaults from `config.py`)
- Backtest switches: `BACKTEST_*`

## Phase 1 — Static Triage (no code changes yet)

**Commands & outputs**
- `python --version`
  - Python 3.10.19
- `pip freeze | head`
  - black==25.12.0
  - click==8.3.1
  - exceptiongroup==1.3.1
  - iniconfig==2.3.0
  - isort==7.0.0
  - librt==0.7.7
  - mypy==1.19.1
  - mypy_extensions==1.1.0
  - nodeenv==1.10.0
  - packaging==25.0
- `pytest -q`
  - Collection failed: missing optional deps (`pandas`, `alpaca`) at import time. See tests section below.
- `rg "TODO|FIXME|HACK|XXX" .`
  - `setup_context.py` contains TODO scaffold; no other code TODOs found.
- `rg "datetime|timezone|tz|pytz|zoneinfo" .`
  - Multiple modules use timezones, including `execution_v2/clocks.py` and `execution_v2/exits.py`.
- `rg "allow_network|network_disallowed|fail_open|fail_closed" .`
  - Universe networking guards and fail-closed language in config and tests.
- `rg "SCHWAB|ETF|universe|allowlist|denylist" .`
  - Strong allowlist enforcement in `execution_v2/live_gate.py` and execution main.
- `ruff check .`
  - Ruff installed; multiple lint issues (imports, style, unused vars). Not addressed in this PR.
- `mypy .`
  - Missing stubs and optional deps (pandas, alpaca, requests, trafilatura). Not addressed in this PR.

### Short triage list of suspected hotspots
- Import-time checks around optional broker/data dependencies (`execution_v2/exits.py`).
- Dry-run ledger write path in `execution_v2/execution_main.py`.
- Config parsing and gating (`execution_v2/live_gate.py`, `execution_v2/execution_main.py`).

## Phase 2 — Contract & Invariant Audit

**Contracts reviewed**
- **Scan output → Portfolio decisions**: `execution_v2/portfolio_decisions.py` normalizes intent/action/gate ordering.
- **Portfolio decisions → Execution**: `execution_v2/execution_main.py` consumes daily candidates and constraints snapshots.
- **Execution → Broker adapter**: `execution_v2/exits.py` (stops), `execution_v2/buy_loop.py` (entries).
- **Execution → Ledger/telemetry**: `execution_v2/exit_events.py`, `analytics/*`.

**Contract gaps / actions**
- Added **config-check** command to validate execution environment (offline) before live execution.

## Phase 3 — Runtime Bug Hunt via Targeted Repros

Added minimal offline repro scripts under `tools/repro/`:
- `invalid_config.py` — invalid config surfaces for execution preflight
- `edge_case_market_data.py` — missing intraday/daily bars
- `order_submission_edge_cases.py` — stop reconciliation with existing sell order
- `ledger_write_failure.py` — dry-run ledger write failure
- `timezone_boundary.py` — market open/close boundary checks

## Phase 4 — Fixes + Tests

### Issue 1 — Alpaca import guard raises ModuleNotFoundError
- **Severity**: Medium
- **Location**: `execution_v2/exits.py` (import-time check for Alpaca exceptions)
- **Symptom**: `ModuleNotFoundError: No module named 'alpaca'` when importing `execution_v2.exits` on machines without the Alpaca SDK.
- **Repro**: `pytest -q` in an environment without the Alpaca SDK (test collection fails).
- **Fix**: Wrap `importlib.util.find_spec` in a `ModuleNotFoundError` guard, and fallback to local `APIError` class.
- **Tests**: `tests/test_exits_import_guard.py`

### Issue 2 — Dry-run ledger path missing creates fail-open idempotency
- **Severity**: Medium
- **Location**: `execution_v2/execution_main.py` dry-run order submission
- **Symptom**: If the state directory is missing, dry-run ledger writes fail and repeated submissions are not de-duplicated.
- **Repro**: `tools/repro/ledger_write_failure.py`
- **Fix**: Centralize state directory resolution, ensure parent directory exists before writing.
- **Tests**: `tests/test_execution_main_dry_run_ledger.py`

### Issue 3 — Missing preflight config check
- **Severity**: Low (operational risk)
- **Location**: `execution_v2/execution_main.py`
- **Symptom**: No offline guard to validate execution env (e.g., missing credentials) prior to systemd restart.
- **Repro**: `tools/repro/invalid_config.py`
- **Fix**: Add `--config-check` CLI flag and `run_config_check()` helper.
- **Tests**: `tests/test_execution_main_config_check.py`

## Not a Bug, but a Risk
- **Missing optional dependencies in local test runs**: `pandas` and `alpaca` are required for some tests; local runs without these dependencies fail during collection. This is expected for minimal environments but should be documented for developers.
- **Ruff/Mypy warnings**: There are numerous lint/type issues (unused imports, module import order, missing stubs). These are not addressed here but represent potential quality debt.

## Recommended Follow-On Hardening Tasks
- [ ] Add `pandas`/`alpaca` optional dependency handling for tests (e.g., skip markers or import guards).
- [ ] Add an explicit schema validator for daily candidates CSV to enforce required columns/types.
- [ ] Add atomic ledger writes (write+rename) for critical ledgers to avoid partial-line corruption.
- [ ] Add a centralized config validation module and reuse it in systemd pre-start hooks.

## Verification

### macOS dev
```bash
python execution_v2/execution_main.py --config-check
pytest -q tests/test_exits_import_guard.py tests/test_execution_main_dry_run_ledger.py tests/test_execution_main_config_check.py
```

### Ubuntu droplet (systemd)
```bash
python execution_v2/execution_main.py --config-check
pytest -q tests/test_exits_import_guard.py tests/test_execution_main_dry_run_ledger.py tests/test_execution_main_config_check.py
systemctl status execution.service --no-pager
```

# Schwab Read-Only Snapshot & Reconciliation (M1-D)

This document describes the **read-only** Schwab PCRA ingestion flow for the
manual Schwab 401(k) book (`SCHWAB_401K_MANUAL`). This phase ingests fixture-backed
broker-truth snapshots and reconciles them against manual intents (M1-B) and
confirmations (M1-C). There are **no execution side effects**.

## Feature flag (default OFF)
Set the feature flag explicitly to run snapshots and reconciliation:

```
export SCHWAB_READONLY_ENABLED=1
```

OAuth scaffolding is **inert** and for later phases only; no network calls are made
in M1-D. The following environment variables are documented for future wiring:

- `SCHWAB_OAUTH_CLIENT_ID`
- `SCHWAB_OAUTH_CLIENT_SECRET`
- `SCHWAB_OAUTH_REDIRECT_URI`
- `SCHWAB_OAUTH_TOKEN_PATH`
- `SCHWAB_OAUTH_AUTH_URL` (default: `https://api.schwabapi.com/v1/oauth/authorize`)
- `SCHWAB_OAUTH_TOKEN_URL` (default: `https://api.schwabapi.com/v1/oauth/token`)

## Fixtures
Snapshots are fixture-backed only. Required fixture files:

```
<fixtures_dir>/meta.json
<fixtures_dir>/balances.json
<fixtures_dir>/positions.json
<fixtures_dir>/orders.json
```

Example `meta.json`:

```json
{
  "as_of_utc": "2026-01-20T16:00:00+00:00",
  "ny_date": "2026-01-20"
}
```

## Running locally (manual)
Run the read-only snapshot + reconciliation CLI:

```
SCHWAB_READONLY_ENABLED=1 \
python -m analytics.schwab_readonly_runner \
  --fixture-dir tests/fixtures/schwab_readonly \
  --book-id SCHWAB_401K_MANUAL
```

Optional flags:
- `--as-of-utc <ISO8601>` overrides `meta.json`.
- `--ny-date <YYYY-MM-DD>` to enforce NY-date alignment.
- `--repo-root <path>` to override the repo root.

## Running on droplet
Copy fixtures to the droplet (Git-first: commit fixtures if they are canonical) and run the
same command with `SCHWAB_READONLY_ENABLED=1`.

## Output locations
Snapshots and reconciliation outputs are append-only JSONL records stored in the Schwab ledger:

```
ledger/SCHWAB_401K_MANUAL/<YYYY-MM-DD>.jsonl
```

Record types introduced in M1-D:
- `SCHWAB_READONLY_ACCOUNT_SNAPSHOT`
- `SCHWAB_READONLY_POSITIONS_SNAPSHOT`
- `SCHWAB_READONLY_ORDERS_SNAPSHOT`
- `SCHWAB_READONLY_RECONCILIATION`

## Drift reason codes
Reconciliation emits deterministic drift reason codes:

- `CONFIRMED_EXECUTED_BUT_NO_POSITION_CHANGE`
- `BROKER_POSITION_CHANGED_BUT_NO_CONFIRMATION`
- `PARTIAL_FILL_MISMATCH`
- `QTY_MISMATCH`
- `UNKNOWN_SYMBOL`

These codes are included at both the per-intent and per-symbol rollup levels, and are
aggregated into the report-level `drift_reason_codes` list.

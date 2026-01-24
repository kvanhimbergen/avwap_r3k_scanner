# Portfolio Throttle (Shadow-Only)

## Purpose
The portfolio throttle artifact is a **shadow-only** output derived from the latest Regime E1 ledger entry. It is
recorded for observability and future portfolio gating work but **does not** alter live execution or sizing today.

## Where It Is Written
Each run appends a JSONL record to:
```
ledger/PORTFOLIO_THROTTLE/{ny_date}.jsonl
```
The ledger file name is keyed off the requested NY date, while the record carries both requested and resolved dates.

## How It Will Be Consumed Later
The portfolio layer will eventually read the most recent throttle record for the requested date and apply the
`risk_multiplier` and `max_new_positions_multiplier` to sizing and/or guardrails. In this phase, it is written only
for auditability.

## Fail-Closed Rules
If the Regime E1 ledger is missing or invalid, the throttle writer still emits a record and defaults to **zero**
multipliers with reason codes indicating the missing regime data. This ensures conservative behavior.

## JSON Schema (Example)
```json
{
  "as_of_utc": "2024-12-31T16:00:00+00:00",
  "requested_ny_date": "2024-12-31",
  "resolved_ny_date": "2024-12-31",
  "provenance": {"module": "analytics.regime_throttle_writer"},
  "record_type": "PORTFOLIO_THROTTLE",
  "schema_version": 1,
  "regime_id": "...",
  "throttle": {
    "schema_version": 1,
    "regime_label": "RISK_ON",
    "confidence": 0.8,
    "risk_multiplier": 1.0,
    "max_new_positions_multiplier": 1.0,
    "reasons": []
  }
}
```

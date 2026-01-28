# RAEC 401(k) Manual Strategy (ETF-only, v1)

## Overview
The RAEC 401(k) manual strategy evaluates an ETF-only allocation model for the Schwab
401(k) book (`SCHWAB_401K_MANUAL`) and **emits manual trade intents** via a single Slack
ticket. The runner is deterministic, offline-first, and **does not place broker orders**.

## Rebalance cadence & gating
The strategy is evaluated weekly (run via CLI with an explicit `--asof YYYY-MM-DD` date).
Slack tickets are sent only when **any** of the following is true:
1. **First evaluation of the month**
2. **Regime change** since the last evaluation
3. **Drift > 3.0%** absolute from target for any holding

Re-running the same `--asof` date is idempotent; duplicate tickets are skipped based on
ledgered intent IDs.

## Setting current allocations
Current allocations are read from the strategy state file. Use the helper CLI to set or
update them:

```bash
python -m strategies.raec_401k_allocs --set VTI=40 QUAL=25 MTUM=20 VTV=10 BIL=5
```

Alternatively, provide a JSON file containing `{ "VTI": 40, "QUAL": 25, ... }`:

```bash
python -m strategies.raec_401k_allocs --from-json /path/to/allocations.json
```

If no current allocations are known, the ticket will include a **notice** and **omit all
order lines**.

## Slack reply protocol
Reply in the Slack thread with one of the statuses below and include the `intent_id`:

- `EXECUTED`
- `PARTIAL`
- `SKIPPED`
- `ERROR`

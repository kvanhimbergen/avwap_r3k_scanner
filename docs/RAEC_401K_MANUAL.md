# RAEC 401(k) Manual Strategy (ETF-only, v1)

## Overview
The RAEC 401(k) manual strategy evaluates an ETF-only allocation model for the Schwab
401(k) book (`SCHWAB_401K_MANUAL`) and **emits manual trade intents** via a single Slack
ticket. The runner is deterministic, offline-first, and **does not place broker orders**.

## Strategy versions
- `RAEC_401K_V1` (`python -m strategies.raec_401k`) is the original static regime allocation model.
- `RAEC_401K_V2` (`python -m strategies.raec_401k_v2`) is a dynamic model with:
  - broader ETF universe (`QQQ`, `SPY`, `IWM`, `QUAL`, `MTUM`, `VTV`, `VEA`, `VWO`, `USMV`, `IEF`, `TLT`, `GLD`, `BIL`)
  - risk-adjusted momentum ranking
  - volatility-targeted risk budget with cash buffer

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

To write allocations for V2 instead of V1, add `--strategy v2`:

```bash
python -m strategies.raec_401k_allocs --strategy v2 --set QQQ=20 QUAL=20 MTUM=20 VTI=20 IEF=10 BIL=10
```

Alternatively, provide a JSON file containing `{ "VTI": 40, "QUAL": 25, ... }`:

```bash
python -m strategies.raec_401k_allocs --from-json /path/to/allocations.json
```

### Updating allocations from Schwab CSV export
Download the Schwab “Positions” CSV export from the workplace portal and ingest it directly:

```bash
python -m strategies.raec_401k_allocs --from-csv /path/to/Schwab-Positions.csv
```

If you prefer a drop-folder workflow, place CSV files in:

```text
state/strategies/SCHWAB_401K_MANUAL/csv_drop/
```

Then ingest the newest file automatically:

```bash
python -m strategies.raec_401k_allocs --from-csv
```

You can also point `--from-csv` at a directory; it will pick the newest `*.csv` there.
Combine this with `--strategy v2` to update the V2 state file.

If a row lacks a ticker symbol, update the `DEFAULT_DESCRIPTION_MAPPING` in
`strategies/raec_401k_allocs.py` to map Schwab fund descriptions to tickers before re-running
the command.

If no current allocations are known, the ticket will include a **notice** and **omit all
order lines**.

## Running V2 (dynamic model)
```bash
python -m strategies.raec_401k_v2 --asof YYYY-MM-DD --dry-run
```

When ready to post a live manual ticket to Slack:

```bash
python -m strategies.raec_401k_v2 --asof YYYY-MM-DD
```

## Slack reply protocol
Reply in the Slack thread with one of the statuses below and include the `intent_id`:

- `EXECUTED`
- `PARTIAL`
- `SKIPPED`
- `ERROR`

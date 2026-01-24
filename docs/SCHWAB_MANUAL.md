# Schwab Manual Slack Ticket Adapter (Outbound)

## Purpose
The Schwab manual book (`SCHWAB_401K_MANUAL`) emits **human-executable** trade tickets via Slack.
Tickets are recorded in an append-only ledger for deterministic idempotency.

## Book ID
- `book_id`: `SCHWAB_401K_MANUAL`

## Ledger Path
```
ledger/SCHWAB_401K_MANUAL/<YYYY-MM-DD>.jsonl
```
Entries are JSONL with `event=MANUAL_TICKET_SENT` and Slack metadata.

## Idempotency
- Each intent is canonicalized (symbol normalization, float formatting, stable key ordering).
- A deterministic hash (`intent_id`) is computed from the canonical payload + `book_id` + `ny_date`.
- On each run, the adapter loads the ledger for the NY date and skips intents already marked `MANUAL_TICKET_SENT`.
- If the ledger is unreadable/invalid, the adapter **fails closed** and raises.

## CLI Smoke Runner (Guarded)
The CLI is a **guarded** helper that only posts to Slack when the environment flag is set:

```bash
SLACK_POST_ENABLED=1 \
python -m execution_v2.schwab_manual_cli \
  --ny-date 2026-01-20 \
  --intents-path path/to/intents.json
```

- `--intents-path` must be a JSON list of intent objects (one per trade).
- If `SLACK_POST_ENABLED` is not set, the CLI will **skip** posting and ledger writes.

## Slack Metadata
Ledger entries include Slack metadata (channel, ts, permalink) when available.
Tests use mock Slack senders; no network calls are required.

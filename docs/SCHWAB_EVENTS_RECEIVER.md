# Schwab Manual Slack Events Receiver (Inbound)

## Purpose
The Schwab manual book (`SCHWAB_401K_MANUAL`) ingests Slack threaded replies and records
manual confirmations (`EXECUTED`, `PARTIAL`, `SKIPPED`, `ERROR`) in the append-only ledger.

## Required Environment Variables
- `SLACK_SIGNING_SECRET` (required): Slack app signing secret.
- `SLACK_EVENTS_CHANNEL_ID` (required): Only accept replies from this channel ID.
- `SLACK_SIGNING_TOLERANCE_SEC` (optional, default `300`): Timestamp replay window.
- `SLACK_EVENTS_BIND_HOST` (optional, default `0.0.0.0`): Bind host.
- `SLACK_EVENTS_BIND_PORT` (optional, default `8081`): Bind port.

## Run Locally
```bash
export SLACK_SIGNING_SECRET="..."
export SLACK_EVENTS_CHANNEL_ID="C1234567890"
python -m execution_v2.slack_events_receiver
```

## Example systemd Unit (Droplet)
```ini
[Unit]
Description=AVWAP Schwab Slack Events Receiver
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/avwap_r3k_scanner
Environment=SLACK_SIGNING_SECRET=...
Environment=SLACK_EVENTS_CHANNEL_ID=C1234567890
Environment=SLACK_EVENTS_BIND_HOST=0.0.0.0
Environment=SLACK_EVENTS_BIND_PORT=8081
ExecStart=/usr/bin/python -m execution_v2.slack_events_receiver
Restart=always

[Install]
WantedBy=multi-user.target
```

## Confirmation Grammar (Threaded Reply)
```
Intent ID: <sha256>
Status: EXECUTED | PARTIAL | SKIPPED | ERROR
Qty: <integer>            # optional
Avg Price: <number>       # optional
Fill Price: <number>      # optional
Notes: <freeform>         # optional
```

Only threaded replies in the configured channel are processed. Invalid or
ambiguous confirmations are recorded as rejected entries with reason codes.

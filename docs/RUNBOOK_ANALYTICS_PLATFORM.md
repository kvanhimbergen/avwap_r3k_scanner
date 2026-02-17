# Runbook: Analytics Platform

Verification and operating steps for the read-only analytics service.

## Preconditions
- Repo deployed at `/root/avwap_r3k_scanner`
- Python virtual env available at `/root/avwap_r3k_scanner/venv`
- `analytics-platform.service` installed from `ops/systemd/analytics-platform.service`

## Install / Update Units
```bash
cd /root/avwap_r3k_scanner
sudo ./ops/install_systemd_units.sh
```

## Service Controls
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now analytics-platform.service
sudo systemctl restart analytics-platform.service
systemctl status analytics-platform.service --no-pager
```

## Health Checks
```bash
curl -sS http://127.0.0.1:8787/api/v1/health | jq .
curl -sS http://127.0.0.1:8787/api/v1/freshness | jq '.data.rows[] | {source_name,parse_status,file_count}'
```

Expected:
- `/health.data.status` is `ok` or `degraded` with explicit error details.
- `/freshness` lists all configured source groups.

## SSH Tunnel (Private Access)
Run locally:
```bash
ssh -L 18787:127.0.0.1:8787 root@<droplet-ip>
```

Open:
- `http://127.0.0.1:18787/api/v1/health`
- If frontend bundle was built: `http://127.0.0.1:18787/app`

## Logs
```bash
journalctl -u analytics-platform.service --since "today" --no-pager
```

## Failure Modes
1. `status=degraded` from `/health`:
- Inspect `refresh_error` in response.
- Confirm source files exist in `ledger/`, `state/`, `backtests/`.
- Rebuild read models manually:
  - `python -m analytics_platform.backend.readmodels.build_readmodels`
2. Service not starting:
- `journalctl -u analytics-platform.service -n 200 --no-pager`
- Verify dependencies in venv (`fastapi`, `duckdb`, `uvicorn`).

## Safety
- The analytics platform is read-only against execution ledgers/state.
- It writes only `analytics_platform/data/analytics.duckdb`.

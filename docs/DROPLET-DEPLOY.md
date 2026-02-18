# Droplet Deployment

## Access

- **App**: http://167.71.186.143:8787/app
- **Health**: http://167.71.186.143:8787/api/v1/health
- **SSH**: `ssh root@167.71.186.143`

## Deploy Workflow

### Frontend changes (CSS, TSX, etc.)

```bash
ssh root@167.71.186.143 "cd /root/avwap_r3k_scanner && git pull && cd analytics_platform/frontend && npm run build && systemctl restart analytics-platform"
```

### Backend-only changes (Python)

```bash
ssh root@167.71.186.143 "cd /root/avwap_r3k_scanner && git pull && systemctl restart analytics-platform"
```

## Service Management

```bash
# Status
ssh root@167.71.186.143 "systemctl status analytics-platform"

# Tail logs
ssh root@167.71.186.143 "journalctl -u analytics-platform -f"

# Restart
ssh root@167.71.186.143 "systemctl restart analytics-platform"
```

## Setup (one-time, already done)

1. Node.js 20 installed via nodesource
2. Python venv at `/root/avwap_r3k_scanner/venv`
3. Systemd unit: `ops/systemd/analytics-platform.service`
4. Installed via `bash ops/install_systemd_units.sh`
5. Server binds to `0.0.0.0:8787` (configurable via `AP_HOST` / `AP_PORT` env vars)
6. UFW is inactive (no firewall rules needed)

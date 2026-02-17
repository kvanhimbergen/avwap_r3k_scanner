# Analytics Platform (AVWAP + S2)

Read-only strategy analytics frontend for monitoring and evaluation.

## Scope
- FastAPI backend with DuckDB read models.
- React frontend with strategy/risk/backtest pages.
- Data sources are append-only ledgers and backtest artifacts.
- No trade controls, no execution writes.

## Paths
- Backend package: `analytics_platform/backend`
- Frontend app: `analytics_platform/frontend`
- DuckDB file: `analytics_platform/data/analytics.duckdb`

## Local Run

### 1) Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2) Build/read models once (optional)
```bash
python -m analytics_platform.backend.readmodels.build_readmodels
```

### 3) Start backend API
```bash
python -m analytics_platform.backend.main
```
API default: `http://127.0.0.1:8787`

### 4) Start frontend (dev)
```bash
cd analytics_platform/frontend
npm install
npm run dev
```
Frontend default: `http://127.0.0.1:8788`

### 5) Optional frontend build served by backend
```bash
cd analytics_platform/frontend
npm run build
```
If `analytics_platform/frontend/dist` exists, backend serves it at `/app`.

## API Endpoints
- `GET /api/v1/health`
- `GET /api/v1/freshness`
- `GET /api/v1/overview`
- `GET /api/v1/strategies/compare`
- `GET /api/v1/decisions/timeseries`
- `GET /api/v1/signals/s2`
- `GET /api/v1/risk/controls`
- `GET /api/v1/backtests/runs`
- `GET /api/v1/backtests/runs/{run_id}`
- `GET /api/v1/exports/{dataset}.csv`

## Read-Only Guarantee
Backend only reads from:
- `ledger/**`
- `state/portfolio_decision_latest.json`
- `backtests/**`

Backend writes only to:
- `analytics_platform/data/analytics.duckdb`

## Droplet Service
Systemd unit:
- `ops/systemd/analytics-platform.service`

Installer script now installs/enables this service:
- `ops/install_systemd_units.sh`

Deploy script restarts it:
- `deploy_systemd.sh`

## SSH Tunnel Access (Private)
From local machine:
```bash
ssh -L 18787:127.0.0.1:8787 -L 18788:127.0.0.1:8788 root@<droplet-ip>
```
Then open:
- API: `http://127.0.0.1:18787/api/v1/health`
- Frontend (dev or preview on droplet): `http://127.0.0.1:18788`

If frontend is served by backend static mount, use:
- `http://127.0.0.1:18787/app`

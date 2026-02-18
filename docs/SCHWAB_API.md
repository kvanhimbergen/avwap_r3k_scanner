# Schwab Trader API — Live Sync

Daily read-only sync of account positions, balances, and orders from the
Schwab Trader API into the ledger via `schwab-py`.

## Setup

### 1. Create a Schwab Developer App

1. Go to [developer.schwab.com](https://developer.schwab.com) and log in
2. Dashboard → Apps → Create App
3. Set callback URL to `https://127.0.0.1`
4. Select the **Trader API** product
5. Submit and wait for approval (1–3 business days)

### 2. Set Environment Variables

Add to `.env`:

```
SCHWAB_READONLY_ENABLED=1
SCHWAB_OAUTH_CLIENT_ID=<App Key from developer portal>
SCHWAB_OAUTH_CLIENT_SECRET=<Secret from developer portal>
SCHWAB_OAUTH_REDIRECT_URI=https://127.0.0.1
SCHWAB_OAUTH_TOKEN_PATH=/Users/<you>/.schwab/token.json
SCHWAB_ACCOUNT_HASH=<from step 3>
```

### 3. Bootstrap OAuth Token

```bash
set -a && source .env && set +a && python -m analytics.schwab_auth
```

This opens a browser for Schwab login. After completing the flow:
- The token is saved to `SCHWAB_OAUTH_TOKEN_PATH`
- Account hashes are printed — copy the one for your account into `SCHWAB_ACCOUNT_HASH`

### 4. Test Live Sync

```bash
set -a && source .env && set +a && python -m analytics.schwab_readonly_runner --live --ny-date 2026-02-18
```

## Token Refresh

Schwab enforces a **7-day hard limit** on refresh tokens. After 7 days the
token stops working and you must re-authenticate.

### Re-authenticate

```bash
set -a && source .env && set +a && python -m analytics.schwab_auth
```

### Check Token Health

```bash
set -a && source .env && set +a && python -c "
from analytics.schwab_token_health import check_token_health
import os
h = check_token_health(os.environ['SCHWAB_OAUTH_TOKEN_PATH'])
print(f'healthy={h.healthy}  days_left={h.days_until_expiry}  reason={h.reason}')
"
```

The runner warns automatically when the token has fewer than 2 days remaining.

## Pipeline Integration

The live sync runs as **optional step 5** in the post-scan pipeline
(`ops/post_scan_pipeline.py`). If the token is expired or credentials are
missing, the step logs a warning and the pipeline continues normally.

## Architecture

| Module | Purpose |
|--------|---------|
| `analytics/schwab_readonly_live_adapter.py` | Calls Schwab API, maps responses to schema dataclasses |
| `analytics/schwab_auth.py` | One-time OAuth bootstrap CLI |
| `analytics/schwab_token_health.py` | Token file validation and expiry check |
| `analytics/schwab_readonly_oauth.py` | OAuth config from environment variables |
| `analytics/schwab_readonly_runner.py` | CLI runner (`--live` or `--fixture-dir`) |

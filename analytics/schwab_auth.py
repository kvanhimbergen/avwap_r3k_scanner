"""One-time OAuth bootstrap CLI for the Schwab Trader API.

Usage:
    python -m analytics.schwab_auth

Runs the browser-based OAuth flow to obtain an initial token file.
After completing the flow, prints available account hashes so you can
set the SCHWAB_ACCOUNT_HASH environment variable.
"""
from __future__ import annotations

from analytics.schwab_readonly_oauth import load_schwab_readonly_oauth_config


def run_auth_flow() -> int:
    config = load_schwab_readonly_oauth_config()
    if not config.client_id or not config.client_secret:
        print("ERROR: SCHWAB_OAUTH_CLIENT_ID and SCHWAB_OAUTH_CLIENT_SECRET must be set")
        return 1
    if not config.redirect_uri:
        print("ERROR: SCHWAB_OAUTH_REDIRECT_URI must be set")
        return 1
    if not config.token_path:
        print("ERROR: SCHWAB_OAUTH_TOKEN_PATH must be set")
        return 1

    import schwab

    print(f"Starting OAuth flow ...")
    print(f"  client_id:    {config.client_id[:8]}...")
    print(f"  redirect_uri: {config.redirect_uri}")
    print(f"  token_path:   {config.token_path}")
    print()

    client = schwab.auth.client_from_manual_flow(
        api_key=config.client_id,
        app_secret=config.client_secret,
        callback_url=config.redirect_uri,
        token_path=config.token_path,
    )

    print(f"\nToken saved to: {config.token_path}")
    print("\nFetching account numbers ...")

    resp = client.get_account_numbers()
    if resp.status_code != 200:
        print(f"WARNING: get_account_numbers returned HTTP {resp.status_code}")
        return 0

    accounts = resp.json()
    if not accounts:
        print("No accounts found.")
        return 0

    print("\nAvailable accounts:")
    for acct in accounts:
        acct_num = acct.get("accountNumber", "?")
        acct_hash = acct.get("hashValue", "?")
        print(f"  accountNumber={acct_num}  hashValue={acct_hash}")

    print("\nSet SCHWAB_ACCOUNT_HASH to the hashValue of the account you want to sync.")
    return 0


def main() -> int:
    return run_auth_flow()


if __name__ == "__main__":
    raise SystemExit(main())

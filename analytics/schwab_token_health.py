"""Token health check for the Schwab OAuth token file.

Validates that the token file exists, is valid JSON, and that the
refresh token has not expired (Schwab enforces a 7-day hard limit).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REFRESH_TOKEN_MAX_AGE_DAYS = 7


@dataclass(frozen=True)
class TokenHealthStatus:
    healthy: bool
    reason: Optional[str]
    days_until_expiry: float


def check_token_health(token_path: str) -> TokenHealthStatus:
    """Check the health of a Schwab OAuth token file.

    Returns a TokenHealthStatus indicating whether the token is usable.
    """
    path = Path(token_path)

    if not path.exists():
        return TokenHealthStatus(
            healthy=False,
            reason=f"token file not found: {token_path}",
            days_until_expiry=0.0,
        )

    try:
        with path.open("r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return TokenHealthStatus(
            healthy=False,
            reason=f"token file unreadable: {exc}",
            days_until_expiry=0.0,
        )

    if not isinstance(data, dict):
        return TokenHealthStatus(
            healthy=False,
            reason="token file is not a JSON object",
            days_until_expiry=0.0,
        )

    if "refresh_token" not in data:
        return TokenHealthStatus(
            healthy=False,
            reason="token file missing refresh_token",
            days_until_expiry=0.0,
        )

    creation_ts = data.get("creation_timestamp")
    if creation_ts is None:
        return TokenHealthStatus(
            healthy=False,
            reason="token file missing creation_timestamp",
            days_until_expiry=0.0,
        )

    try:
        created_at = float(creation_ts)
    except (TypeError, ValueError):
        return TokenHealthStatus(
            healthy=False,
            reason=f"invalid creation_timestamp: {creation_ts}",
            days_until_expiry=0.0,
        )

    now = time.time()
    age_seconds = now - created_at
    age_days = age_seconds / 86400.0
    days_until_expiry = REFRESH_TOKEN_MAX_AGE_DAYS - age_days

    if days_until_expiry <= 0:
        return TokenHealthStatus(
            healthy=False,
            reason=f"refresh token expired ({age_days:.1f} days old, max {REFRESH_TOKEN_MAX_AGE_DAYS})",
            days_until_expiry=0.0,
        )

    return TokenHealthStatus(
        healthy=True,
        reason=None,
        days_until_expiry=round(days_until_expiry, 2),
    )

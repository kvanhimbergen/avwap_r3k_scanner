"""
Execution V2 – Alerting Wrapper

This module provides a thin abstraction over the existing Slack alerting
infrastructure. Execution logic should depend only on this interface.

Alerting is best-effort and must never block execution.
"""

from __future__ import annotations

import sys
import traceback
from typing import Optional


def _safe_print(msg: str) -> None:
    # journald capture via stdout
    print(msg, flush=True)


def send_alert(
    title: str,
    message: str,
    level: str = "info",
    symbol: Optional[str] = None,
) -> None:
    """
    Send an alert. This must never raise.
    """
    try:
        # Lazy import to avoid hard dependency at startup
        from alerts.slack import send_slack_message  # existing infra

        prefix = f"[{level.upper()}]"
        if symbol:
            prefix += f" [{symbol}]"

        text = f"{prefix} {title}\n{message}"
        send_slack_message(text)

    except Exception:
        _safe_print("[alerts] Slack alert failed:")
        traceback.print_exc(file=sys.stdout)
# Execution V2 placeholder: alerts.py

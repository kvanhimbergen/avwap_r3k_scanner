#!/usr/bin/env python
"""
Repro: invalid configuration surfaces for execution_v2 config check.
"""

from __future__ import annotations

import os
from execution_v2 import execution_main


def main() -> None:
    os.environ["EXECUTION_MODE"] = "ALPACA_PAPER"
    os.environ.pop("APCA_API_KEY_ID", None)
    os.environ.pop("APCA_API_SECRET_KEY", None)
    os.environ.pop("APCA_API_BASE_URL", None)

    ok, issues = execution_main.run_config_check(state_dir="/tmp/avwap_state")
    print("config_check_ok=", ok)
    for issue in issues:
        print("issue:", issue)


if __name__ == "__main__":
    main()

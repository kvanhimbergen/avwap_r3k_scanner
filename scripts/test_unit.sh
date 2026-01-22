#!/usr/bin/env bash
set -euo pipefail

pytest -q tests/test_execution_v2_live_gate.py
pytest -q -m "not requires_pandas and not requires_numpy"

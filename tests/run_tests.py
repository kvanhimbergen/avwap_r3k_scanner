
"""Run all tests with: python tests/run_tests.py

This is the single source of truth for the test entrypoint in CI and operator workflows.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
import os


def _pytest_available() -> bool:
    return importlib.util.find_spec("pytest") is not None


def main() -> int:
    if not _pytest_available():
        print("FAIL: pytest is not installed.")
        print("Install it with: pip install -r requirements-dev.txt")
        print("Or: pip install pytest")
        return 1

    root = Path(__file__).resolve().parents[1]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)

    tests = [
        root / "tests" / "test_analytics_determinism.py",
        root / "tests" / "test_analytics_ledgers.py",
        root / "tests" / "test_analytics_metrics.py",
        root / "tests" / "test_analytics_metrics_storage.py",
        root / "tests" / "test_analytics_reconstruction.py",
        root / "tests" / "test_book_router.py",
        root / "tests" / "test_analytics_storage.py",
        root / "tests" / "test_portfolio_snapshot.py",
        root / "tests" / "test_portfolio_daily_snapshot.py",
        root / "tests" / "test_reconciliation.py",
        root / "tests" / "test_exit_event_determinism.py",
        root / "tests" / "test_exit_event_schema.py",
        root / "tests" / "test_exit_mae_mfe.py",
        root / "tests" / "test_exit_simulator_parity.py",
        root / "tests" / "test_backtest_engine.py",
        root / "tests" / "test_backtest_guardrails.py",
        root / "tests" / "test_backtest_observability.py",
        root / "tests" / "test_backtest_sizing.py",
        root / "tests" / "test_ci_docs_trust.py",
        root / "tests" / "test_portfolio_decision_contract.py",
        root / "tests" / "test_portfolio_decision_shadow.py",
        root / "tests" / "test_portfolio_decision_enforcement.py",
        root / "tests" / "test_pytest_collect_only_regression.py",
        root / "tests" / "test_determinism.py",
        root / "tests" / "test_execution_v2_live_gate.py",
        root / "tests" / "test_intraday_higher_low_stop.py",
        root / "tests" / "test_stop_reconcile_guardrails.py",
        root / "tests" / "test_alpaca_paper_invariants.py",
        root / "tests" / "test_paper_sim_idempotency.py",
        root / "tests" / "test_paper_sim_pricing.py",
        root / "tests" / "test_paper_sim_routing_invariant.py",
        root / "tests" / "test_no_lookahead.py",
        root / "tests" / "test_parity_scan_backtest.py",
        root / "tests" / "test_provenance.py",
        root / "tests" / "test_scan_engine_schema.py",
        root / "tests" / "test_slack_notifications.py",
        root / "tests" / "test_sweep_runner.py",
        root / "tests" / "test_schwab_manual_adapter.py",
        root / "tests" / "test_schwab_manual_confirmation_parser.py",
        root / "tests" / "test_slack_events_receiver.py",
        root / "tests" / "test_schwab_readonly_adapter.py",
        root / "tests" / "test_schwab_readonly_no_execution_imports.py",
        root / "tests" / "test_schwab_readonly_reconciliation.py",
        root / "tests" / "test_schwab_readonly_schemas.py",
        root / "tests" / "test_schwab_readonly_storage.py",
        root / "tests" / "test_regime_e1_classifier.py",
        root / "tests" / "test_regime_e1_date_resolution.py",
        root / "tests" / "test_regime_e1_features.py",
        root / "tests" / "test_regime_e1_no_execution_imports.py",
        root / "tests" / "test_regime_policy.py",
        root / "tests" / "test_scan_engine_benchmark_refresh.py",
        root / "tests" / "test_execution_v2_no_analytics_imports.py",
        root / "tests" / "test_universe.py",
        root / "tests" / "test_setup_context_contract.py",
        root / "tests" / "test_portfolio_throttle_writer.py",
    ]

    any_fail = False
    for test_path in tests:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path)],
            env=env,
        )
        if result.returncode == 0:
            print(f"PASS: {test_path}")
        else:
            print(f"FAIL: {test_path}")
            any_fail = True

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

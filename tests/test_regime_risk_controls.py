from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from portfolio import risk_controls


def _write_throttle_record(path: Path, *, risk_multiplier: float, max_new_positions_multiplier: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "as_of_utc": "2024-01-02T16:00:00+00:00",
        "requested_ny_date": "2024-01-02",
        "resolved_ny_date": "2024-01-02",
        "record_type": risk_controls.RECORD_TYPE_THROTTLE,
        "schema_version": 1,
        "throttle": {
            "schema_version": 1,
            "regime_label": "NEUTRAL",
            "confidence": 0.8,
            "risk_multiplier": risk_multiplier,
            "max_new_positions_multiplier": max_new_positions_multiplier,
            "reasons": [],
        },
    }
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def test_feature_flag_off_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(risk_controls.FEATURE_FLAG_ENV, "0")
    result = risk_controls.build_risk_controls(
        ny_date="2024-01-02",
        repo_root=tmp_path,
        base_max_positions=10,
        base_max_gross_exposure=1.0,
        base_per_position_cap=0.2,
        enabled=None,
        write_ledger=True,
    )
    assert result.record is None
    assert result.controls.risk_multiplier == 1.0
    assert result.controls.max_gross_exposure == pytest.approx(1.0)
    assert result.controls.max_positions == 10
    assert result.controls.per_position_cap == pytest.approx(0.2)
    assert result.controls.throttle_reason == "disabled"
    assert not (tmp_path / "ledger" / "PORTFOLIO_RISK_CONTROLS").exists()


def test_throttle_mapping_applies_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(risk_controls.FEATURE_FLAG_ENV, "1")
    throttle_path = (
        tmp_path
        / "ledger"
        / "PORTFOLIO_THROTTLE"
        / "2024-01-02.jsonl"
    )
    _write_throttle_record(throttle_path, risk_multiplier=0.6, max_new_positions_multiplier=0.5)

    result = risk_controls.build_risk_controls(
        ny_date="2024-01-02",
        repo_root=tmp_path,
        base_max_positions=10,
        base_max_gross_exposure=1.0,
        base_per_position_cap=0.2,
        drawdown=0.1,
        max_drawdown_pct_block=0.2,
    )

    controls = result.controls
    assert controls.risk_multiplier == pytest.approx(0.6)
    assert controls.max_positions == 5
    assert controls.max_gross_exposure == pytest.approx(0.6)
    assert controls.per_position_cap == pytest.approx(0.12)
    assert controls.throttle_reason == "ok"

    ledger_path = tmp_path / "ledger" / "PORTFOLIO_RISK_CONTROLS" / "2024-01-02.jsonl"
    assert ledger_path.exists()
    content = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 1


def test_drawdown_composition_is_monotonic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(risk_controls.FEATURE_FLAG_ENV, "1")
    throttle_path = (
        tmp_path
        / "ledger"
        / "PORTFOLIO_THROTTLE"
        / "2024-01-03.jsonl"
    )
    _write_throttle_record(throttle_path, risk_multiplier=0.6, max_new_positions_multiplier=0.5)

    result = risk_controls.build_risk_controls(
        ny_date="2024-01-03",
        repo_root=tmp_path,
        base_max_positions=10,
        base_max_gross_exposure=1.0,
        base_per_position_cap=0.2,
        drawdown=0.3,
        max_drawdown_pct_block=0.2,
    )

    assert result.controls.risk_multiplier == pytest.approx(0.0)
    assert "drawdown_guardrail" in result.reasons


def test_risk_controls_deterministic(tmp_path: Path) -> None:
    throttle_path = (
        tmp_path
        / "ledger"
        / "PORTFOLIO_THROTTLE"
        / "2024-01-04.jsonl"
    )
    _write_throttle_record(throttle_path, risk_multiplier=0.6, max_new_positions_multiplier=0.5)

    result_a = risk_controls.build_risk_controls(
        ny_date="2024-01-04",
        repo_root=tmp_path,
        base_max_positions=10,
        base_max_gross_exposure=1.0,
        base_per_position_cap=0.2,
        drawdown=0.1,
        max_drawdown_pct_block=0.2,
        enabled=True,
        write_ledger=False,
    )
    result_b = risk_controls.build_risk_controls(
        ny_date="2024-01-04",
        repo_root=tmp_path,
        base_max_positions=10,
        base_max_gross_exposure=1.0,
        base_per_position_cap=0.2,
        drawdown=0.1,
        max_drawdown_pct_block=0.2,
        enabled=True,
        write_ledger=False,
    )

    assert result_a.controls == result_b.controls
    assert result_a.reasons == result_b.reasons


def test_adjust_order_quantity_blocks_when_multiplier_zero() -> None:
    controls = risk_controls.RiskControls(
        risk_multiplier=0.0,
        max_gross_exposure=None,
        max_positions=None,
        per_position_cap=None,
        throttle_reason="drawdown_guardrail",
    )

    qty = risk_controls.adjust_order_quantity(
        base_qty=10,
        price=100.0,
        account_equity=100_000.0,
        risk_controls=controls,
        gross_exposure=None,
        min_qty=None,
    )
    assert qty == 0


def test_adjust_order_quantity_caps_pct_gross_exposure() -> None:
    controls = risk_controls.RiskControls(
        risk_multiplier=1.0,
        max_gross_exposure=0.5,
        max_positions=None,
        per_position_cap=None,
        throttle_reason="ok",
    )

    qty = risk_controls.adjust_order_quantity(
        base_qty=200,
        price=10.0,
        account_equity=1_000.0,
        risk_controls=controls,
        gross_exposure=400.0,
        min_qty=None,
    )
    assert qty == 10


def test_adjust_order_quantity_caps_absolute_gross_exposure() -> None:
    controls = risk_controls.RiskControls(
        risk_multiplier=1.0,
        max_gross_exposure=5_000.0,
        max_positions=None,
        per_position_cap=None,
        throttle_reason="ok",
    )

    qty = risk_controls.adjust_order_quantity(
        base_qty=200,
        price=10.0,
        account_equity=1_000.0,
        risk_controls=controls,
        gross_exposure=4_800.0,
        min_qty=None,
    )
    assert qty == 20


def test_resolve_drawdown_from_snapshot_numeric(tmp_path: Path) -> None:
    snapshot = {"metrics": {"drawdown": 0.12}}
    path = tmp_path / "2024-01-02.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    drawdown, reasons = risk_controls.resolve_drawdown_from_snapshot(base_dir=str(tmp_path))
    assert drawdown == pytest.approx(0.12)
    assert reasons == []


def test_resolve_drawdown_from_snapshot_dict(tmp_path: Path) -> None:
    snapshot = {"metrics": {"drawdown": {"max_drawdown": -0.25, "series": []}}}
    path = tmp_path / "2024-01-03.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    drawdown, reasons = risk_controls.resolve_drawdown_from_snapshot(base_dir=str(tmp_path))
    assert drawdown == pytest.approx(-0.25)
    assert reasons == []


def test_resolve_drawdown_from_snapshot_missing_max(tmp_path: Path) -> None:
    snapshot = {"metrics": {"drawdown": {"series": []}}}
    path = tmp_path / "2024-01-04.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    drawdown, reasons = risk_controls.resolve_drawdown_from_snapshot(base_dir=str(tmp_path))
    assert drawdown is None
    assert reasons == ["portfolio_snapshot_invalid"]


def test_resolve_drawdown_from_snapshot_invalid_value(tmp_path: Path) -> None:
    snapshot = {"metrics": {"drawdown": {"max_drawdown": "bad"}}}
    path = tmp_path / "2024-01-05.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    drawdown, reasons = risk_controls.resolve_drawdown_from_snapshot(base_dir=str(tmp_path))
    assert drawdown is None
    assert reasons == ["portfolio_snapshot_invalid"]


def test_offline_artifacts_only() -> None:
    source = Path(risk_controls.__file__).read_text(encoding="utf-8")
    assert "yfinance" not in source

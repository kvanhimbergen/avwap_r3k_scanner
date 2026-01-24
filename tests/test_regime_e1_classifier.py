from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

pytestmark = pytest.mark.requires_pandas

from analytics.regime_e1_classifier import classify_regime
from analytics.regime_e1_features import compute_regime_features
from analytics.regime_e1_schemas import build_regime_id, stable_json_dumps
from analytics.regime_e1_storage import build_record, write_record


def _make_history(symbols: list[str], days: int = 260) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=days, freq="B")
    rows = []
    for symbol in symbols:
        price = 100.0
        for dt in dates:
            price *= 1.001
            rows.append({
                "Date": dt,
                "Ticker": symbol,
                "Close": price,
            })
    return pd.DataFrame(rows)


def test_regime_determinism_and_label(tmp_path: Path) -> None:
    history = _make_history(["SPY", "IWM"])
    ny_date = history["Date"].max().date().isoformat()

    feature_result = compute_regime_features(history, ny_date)
    assert feature_result.ok
    classification = classify_regime(feature_result.feature_set)
    record = build_record(
        record_type="REGIME_E1_SIGNAL",
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        payload={
            "regime_label": classification.regime_label,
            "confidence": classification.confidence,
            "signals": classification.signals,
            "inputs_snapshot": classification.inputs_snapshot,
            "reason_codes": classification.reason_codes,
        },
    )

    feature_result_b = compute_regime_features(history, ny_date)
    classification_b = classify_regime(feature_result_b.feature_set)
    record_b = build_record(
        record_type="REGIME_E1_SIGNAL",
        ny_date=ny_date,
        as_of_utc=f"{ny_date}T16:00:00+00:00",
        payload={
            "regime_label": classification_b.regime_label,
            "confidence": classification_b.confidence,
            "signals": classification_b.signals,
            "inputs_snapshot": classification_b.inputs_snapshot,
            "reason_codes": classification_b.reason_codes,
        },
    )

    assert classification.regime_label == "RISK_ON"
    assert record["regime_id"] == record_b["regime_id"]

    repo_root = tmp_path / "repo"
    result = write_record(repo_root=repo_root, ny_date=ny_date, record=record)
    result_repeat = write_record(repo_root=repo_root, ny_date=ny_date, record=record)
    assert result.records_written == 1
    assert result_repeat.skipped == 1
    ledger_path = Path(result.ledger_path)
    lines = ledger_path.read_text().strip().splitlines()
    assert len(lines) == 1


def test_regime_id_stable_across_key_order() -> None:
    payload_a = {"b": 2, "a": 1}
    payload_b = {"a": 1, "b": 2}
    id_a = build_regime_id(payload_a)
    id_b = build_regime_id(payload_b)
    assert id_a == id_b
    assert stable_json_dumps(payload_a) == stable_json_dumps(payload_b)


def test_missing_inputs_skip_reason() -> None:
    history = _make_history(["IWM"])
    ny_date = history["Date"].max().date().isoformat()
    result = compute_regime_features(history, ny_date)
    assert not result.ok
    assert "missing_symbol_spy" in result.reason_codes

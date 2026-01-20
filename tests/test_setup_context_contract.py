import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from setup_context import compute_setup_context_contract
from tests.helpers import (
    assert_no_forbidden_keys,
    assert_numeric_features_finite,
    assert_trace_outputs_exist,
    make_ohlcv,
    make_setup_rules,
)


def _compute_ctx(
    *,
    df: pd.DataFrame | None = None,
    rules: dict | None = None,
    anchor_name: str | None = None,
    computed_at: str | None = None,
) -> dict:
    data = df if df is not None else make_ohlcv("2024-01-01", 12, gap=True)
    rule_set = rules if rules is not None else make_setup_rules()
    return compute_setup_context_contract(
        data,
        "TEST",
        data.index[-1].date().isoformat(),
        anchor_name=anchor_name,
        rules=rule_set,
        computed_at=computed_at,
    )


def test_setup_context_has_required_top_level_keys() -> None:
    ctx = _compute_ctx()
    assert set(ctx.keys()) == {"schema", "identity", "provenance", "labels", "features", "trace"}


def test_setup_context_schema_fields() -> None:
    ctx = _compute_ctx()
    assert ctx["schema"]["name"] == "setup_context"
    assert ctx["schema"]["version"] == 1


def test_setup_context_identity_fields() -> None:
    ctx = _compute_ctx()
    identity = ctx["identity"]
    assert identity["symbol"] == "TEST"
    assert identity["scan_date"] == ctx["identity"]["scan_date"]
    assert identity["timezone"] == "America/New_York"
    assert identity["session"] == "RTH"


def test_provenance_contains_rules_version_and_hash() -> None:
    ctx = _compute_ctx()
    prov = ctx["provenance"]
    assert isinstance(prov["setup_rules_version"], int)
    assert prov["setup_rules_version"] >= 2
    assert prov["setup_rules_hash"].startswith("sha256:")


def test_provenance_computed_at_is_iso8601() -> None:
    ctx = _compute_ctx()
    computed_at = ctx["provenance"]["computed_at"]
    assert datetime.fromisoformat(computed_at)


def test_provenance_data_window_exists() -> None:
    ctx = _compute_ctx()
    data_window = ctx["provenance"]["data_window"]
    assert data_window["daily_lookback_days"] > 0
    assert isinstance(data_window["intraday_used"], bool)
    assert "intraday_granularity" in data_window


def test_labels_modules_present_and_valid() -> None:
    ctx = _compute_ctx()
    modules = ctx["labels"]["modules"]
    expected = {
        "vwap_context",
        "avwap_context",
        "extension_awareness",
        "gap_context",
        "structure_confirmation",
    }
    assert set(modules.keys()) == expected
    for value in modules.values():
        assert value in {"enabled", "disabled", "na"}


def test_disabled_modules_do_not_emit_inconsistent_fields() -> None:
    rules = make_setup_rules(extension_enabled=False, gap_enabled=False, structure_enabled=False)
    ctx = _compute_ctx(rules=rules)
    assert ctx["labels"]["modules"]["extension_awareness"] == "disabled"
    assert ctx["labels"]["extension"]["label"] == "na"
    assert ctx["labels"]["gap"]["has_gap"] is False
    assert ctx["labels"]["structure"]["trend"] == "unknown"


def test_required_label_fields_exist() -> None:
    ctx = _compute_ctx()
    labels = ctx["labels"]
    assert "vwap" in labels
    assert "avwap" in labels
    assert "extension" in labels
    assert "gap" in labels
    assert "structure" in labels
    assert "modules" in labels


def test_vwap_control_label_enum() -> None:
    ctx = _compute_ctx()
    assert ctx["labels"]["vwap"]["control_label"] in {
        "buyers_in_control",
        "sellers_in_control",
        "balanced_or_indecisive",
    }


def test_vwap_reclaim_acceptance_label_enum() -> None:
    ctx = _compute_ctx()
    assert ctx["labels"]["vwap"]["reclaim_acceptance_label"] in {
        "below_vwap",
        "reclaiming_vwap",
        "accepted_above_vwap",
    }


def test_extension_label_enum() -> None:
    ctx = _compute_ctx()
    assert ctx["labels"]["extension"]["label"] in {
        "compressed_near_value",
        "moderately_extended",
        "overextended_from_value",
        "na",
    }


def test_gap_fields_valid() -> None:
    ctx = _compute_ctx()
    gap = ctx["labels"]["gap"]
    assert isinstance(gap["has_gap"], bool)
    assert gap["direction"] in {"up", "down", "none"}
    if gap["has_gap"]:
        assert isinstance(gap["gap_pct"], float)


def test_structure_enums_valid() -> None:
    ctx = _compute_ctx()
    struct = ctx["labels"]["structure"]
    assert struct["trend"] in {"uptrend", "downtrend", "range", "unknown"}
    assert struct["confirmation"] in {"confirmed", "conflicted", "caution", "unknown"}


def test_avwap_per_anchor_states_valid_when_enabled() -> None:
    ctx = _compute_ctx(anchor_name="major_high")
    per_anchor = ctx["labels"]["avwap"]["per_anchor"]
    for anchor, data in per_anchor.items():
        assert data["state_label"] in {
            "supply_overhead",
            "reclaiming_avwap",
            "demand_underfoot",
            "na",
        }
        assert data["relation"] in {"above", "below", "around", "unknown"}
        assert data["relevance"] in {"relevant", "far", "unknown"}
        assert anchor in {"major_high", "major_low"}


def test_avwap_key_anchor_coherence() -> None:
    ctx = _compute_ctx(anchor_name="major_high")
    key_anchor = ctx["labels"]["avwap"].get("key_anchor")
    assert key_anchor is not None
    assert key_anchor["anchor_type"] in ctx["labels"]["avwap"]["per_anchor"]


def test_features_echo_thresholds_and_parameters() -> None:
    rules = make_setup_rules(gap_threshold_pct=5.0)
    ctx = _compute_ctx(rules=rules)
    features = ctx["features"]
    assert features["gap_threshold_pct"] == 5.0
    assert features["vwap_acceptance_days"] == 2
    assert features["structure_sma_fast"] == 3


def test_numeric_features_are_finite() -> None:
    ctx = _compute_ctx()
    assert_numeric_features_finite(ctx["features"])


def test_extension_reference_consistency() -> None:
    ctx = _compute_ctx(anchor_name="major_high")
    reference = ctx["labels"]["extension"]["reference"]
    assert reference["type"] in {"vwap", "avwap"}
    if ctx["labels"]["modules"]["avwap_context"] == "enabled":
        assert reference["type"] == "avwap"


def test_trace_exists_and_has_valid_entries() -> None:
    ctx = _compute_ctx()
    trace = ctx["trace"]
    assert isinstance(trace, list)
    assert trace
    for entry in trace:
        assert set(entry.keys()) == {"rule_id", "module", "fired", "inputs", "outputs"}


def test_trace_outputs_reference_existing_paths() -> None:
    ctx = _compute_ctx()
    assert_trace_outputs_exist(ctx)


def test_trace_rule_ids_are_stable_strings() -> None:
    ctx = _compute_ctx()
    for entry in ctx["trace"]:
        assert isinstance(entry["rule_id"], str)
        assert entry["rule_id"]


def test_trace_contains_core_label_decisions_when_enabled() -> None:
    ctx = _compute_ctx(anchor_name="major_high")
    outputs = [out for entry in ctx["trace"] for out in entry["outputs"]]
    assert "labels.vwap.control_label" in outputs
    assert "labels.extension.label" in outputs
    assert "labels.structure.trend" in outputs
    assert any(output.startswith("labels.avwap.per_anchor.") for output in outputs)


def test_setup_context_contains_no_execution_intent_keys() -> None:
    ctx = _compute_ctx()
    assert_no_forbidden_keys(ctx)


def test_labels_do_not_include_long_short_intent() -> None:
    ctx = _compute_ctx()
    labels = ctx["labels"]
    label_values = [
        value
        for section in labels.values()
        if isinstance(section, dict)
        for value in section.values()
        if isinstance(value, str)
    ]
    assert "long" not in [val.lower() for val in label_values]
    assert "short" not in [val.lower() for val in label_values]


def test_compute_setup_context_is_deterministic_for_same_inputs() -> None:
    data = make_ohlcv("2024-01-01", 12)
    rules = make_setup_rules()
    computed_at = "2024-06-01T12:00:00+00:00"
    first = _compute_ctx(df=data, rules=rules, computed_at=computed_at)
    second = _compute_ctx(df=data, rules=rules, computed_at=computed_at)
    assert first == second


def test_missing_vwap_sets_unknown_relations_and_labels() -> None:
    rules = make_setup_rules(vwap_lookback=10)
    df = make_ohlcv("2024-01-01", 3)
    ctx = _compute_ctx(df=df, rules=rules)
    vwap = ctx["labels"]["vwap"]
    assert vwap["control_label"] == "balanced_or_indecisive"
    assert vwap["control_relation"] == "unknown"


def test_missing_avwap_anchor_type_is_na_not_error() -> None:
    ctx = _compute_ctx(anchor_name="unknown_anchor")
    per_anchor = ctx["labels"]["avwap"]["per_anchor"]
    for anchor in per_anchor.values():
        assert anchor["state_label"] == "na"


def test_setup_context_does_not_reject_candidates_based_on_universe_rules() -> None:
    df = make_ohlcv("2024-01-01", 12)
    df["Close"] = np.linspace(1.0, 2.0, len(df))
    df["Volume"] = 100.0
    ctx = _compute_ctx(df=df)
    assert ctx["identity"]["symbol"] == "TEST"

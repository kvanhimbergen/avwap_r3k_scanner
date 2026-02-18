from __future__ import annotations

import json
from pathlib import Path

from execution_v2 import portfolio_decision_enforce


def _write_decision_batch(base_dir: Path, date_ny: str, decisions: list[dict], payload_date_ny: str | None = None) -> Path:
    payload = {
        "date": (payload_date_ny or date_ny),
        "generated_at": f"{date_ny}T00:00:00+00:00",
        "decisions": decisions,
    }
    path = base_dir / f"{date_ny}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def _decision(
    date_ny: str,
    symbol: str,
    decision: str = "ALLOW",
    reason_codes: list[str] | None = None,
) -> dict:
    if reason_codes is None:
        reason_codes = ["ALLOW_WITHIN_LIMITS"] if decision == "ALLOW" else ["LIMIT_MAX_OPEN_POSITIONS"]
    return {
        "decision_id": f"id-{symbol}",
        "date": date_ny,
        "symbol": symbol,
        "decision": decision,
        "reason_codes": list(reason_codes),
        "inputs_used": ["daily_candidates.csv"],
    }


def test_enforcement_flag_off(monkeypatch) -> None:
    monkeypatch.delenv("PORTFOLIO_DECISION_ENFORCE", raising=False)
    assert portfolio_decision_enforce.enforcement_enabled() is False
    monkeypatch.setenv("PORTFOLIO_DECISION_ENFORCE", "0")
    assert portfolio_decision_enforce.enforcement_enabled() is False


def test_missing_decision_file_blocks(tmp_path) -> None:
    date_ny = "2024-01-02"
    context = portfolio_decision_enforce.load_decision_context(date_ny, base_dir=str(tmp_path))
    result = portfolio_decision_enforce.evaluate_action("entry", "AAPL", context)
    assert result.decision == "BLOCK"
    assert result.reason_codes == ["DECISION_FILE_MISSING"]


def test_date_mismatch_blocks(tmp_path) -> None:
    date_ny = "2024-01-02"
    _write_decision_batch(tmp_path, date_ny, [_decision("2024-01-01", "AAPL")], payload_date_ny="2024-01-01")
    context = portfolio_decision_enforce.load_decision_context(date_ny, base_dir=str(tmp_path))
    result = portfolio_decision_enforce.evaluate_action("entry", "AAPL", context)
    assert result.decision == "BLOCK"
    assert result.reason_codes == ["DECISION_DATE_MISMATCH"]


def test_symbol_missing_blocks(tmp_path) -> None:
    date_ny = "2024-01-02"
    _write_decision_batch(tmp_path, date_ny, [_decision(date_ny, "MSFT")])
    context = portfolio_decision_enforce.load_decision_context(date_ny, base_dir=str(tmp_path))
    result = portfolio_decision_enforce.evaluate_action("entry", "AAPL", context)
    assert result.decision == "BLOCK"
    assert result.reason_codes == ["DECISION_SYMBOL_NOT_FOUND"]


def test_block_decision_blocks(tmp_path) -> None:
    date_ny = "2024-01-02"
    _write_decision_batch(
        tmp_path,
        date_ny,
        [_decision(date_ny, "AAPL", decision="BLOCK", reason_codes=["LIMIT_MAX_OPEN_POSITIONS"])],
    )
    context = portfolio_decision_enforce.load_decision_context(date_ny, base_dir=str(tmp_path))
    result = portfolio_decision_enforce.evaluate_action("entry", "AAPL", context)
    assert result.decision == "BLOCK"
    assert result.reason_codes == ["LIMIT_MAX_OPEN_POSITIONS"]


def test_allow_decision_allows(tmp_path) -> None:
    date_ny = "2024-01-02"
    _write_decision_batch(tmp_path, date_ny, [_decision(date_ny, "AAPL")])
    context = portfolio_decision_enforce.load_decision_context(date_ny, base_dir=str(tmp_path))
    result = portfolio_decision_enforce.evaluate_action("entry", "AAPL", context)
    assert result.decision == "ALLOW"
    assert result.reason_codes == ["ALLOW_WITHIN_LIMITS"]


def test_exits_not_blocked(tmp_path) -> None:
    date_ny = "2024-01-02"
    context = portfolio_decision_enforce.load_decision_context(date_ny, base_dir=str(tmp_path))
    result = portfolio_decision_enforce.evaluate_action("exit", "AAPL", context)
    assert result.decision == "ALLOW"
    assert result.enforced is False
    assert result.reason_codes == []


def test_enforcement_telemetry_jsonl_deterministic(tmp_path) -> None:
    date_ny = "2024-01-02"
    path = portfolio_decision_enforce.resolve_enforcement_artifact_path(
        date_ny, base_dir=str(tmp_path)
    )
    record_b = portfolio_decision_enforce.build_enforcement_record(
        date_ny=date_ny,
        symbol="MSFT",
        decision="BLOCK",
        enforced=True,
        reason_codes=["DECISION_SYMBOL_NOT_FOUND"],
        decision_id=None,
        decision_artifact_path="/tmp/decisions.json",
        decision_batch_generated_at=None,
    )
    record_a = portfolio_decision_enforce.build_enforcement_record(
        date_ny=date_ny,
        symbol="AAPL",
        decision="ALLOW",
        enforced=True,
        reason_codes=["ALLOW_WITHIN_LIMITS"],
        decision_id="id-aapl",
        decision_artifact_path="/tmp/decisions.json",
        decision_batch_generated_at=f"{date_ny}T00:00:00+00:00",
    )
    portfolio_decision_enforce.write_enforcement_records([record_b, record_a], path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert [item["symbol"] for item in parsed] == ["AAPL", "MSFT"]
    assert lines[0].startswith("{\"date_ny\"")


def test_slack_alert_summary_ordering() -> None:
    records = [
        {"symbol": "MSFT", "decision": "BLOCK", "reason_codes": ["Z_REASON"]},
        {"symbol": "AAPL", "decision": "BLOCK", "reason_codes": ["DECISION_FILE_MISSING"]},
        {"symbol": "TSLA", "decision": "ALLOW", "reason_codes": ["ALLOW_WITHIN_LIMITS"]},
    ]
    blocked_symbols, reason_codes = portfolio_decision_enforce.summarize_blocked_records(records)
    assert blocked_symbols == ["AAPL", "MSFT"]
    assert reason_codes == ["DECISION_FILE_MISSING", "Z_REASON"]

    calls: list[tuple] = []

    def _slack_sender(level, title, message, component, throttle_key, throttle_seconds, **kwargs) -> None:
        calls.append((level, title, message, component, throttle_key, throttle_seconds))

    portfolio_decision_enforce.send_blocked_alert(
        date_ny="2024-01-02",
        blocked_symbols=blocked_symbols,
        reason_codes=reason_codes,
        slack_sender=_slack_sender,
    )
    assert calls
    _, _, message, _, _, _ = calls[0]
    assert "blocked=[AAPL, MSFT]" in message
    assert "reasons=[DECISION_FILE_MISSING, Z_REASON]" in message

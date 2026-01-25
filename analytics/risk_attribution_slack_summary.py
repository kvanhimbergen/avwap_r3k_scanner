from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

FEATURE_FLAG_ENV = "E3_RISK_ATTRIBUTION_SLACK_SUMMARY"
DEFAULT_WINDOW_LABEL = "20D"


def slack_summary_enabled() -> bool:
    return os.getenv(FEATURE_FLAG_ENV, "0").strip() == "1"


def resolve_daily_summary_path(*, as_of: str, ledger_root: Path) -> Path:
    return ledger_root / "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY" / f"{as_of}.json"


def resolve_rolling_summary_path(
    *,
    as_of: str,
    ledger_root: Path,
    window_label: str = DEFAULT_WINDOW_LABEL,
) -> Path:
    return ledger_root / "PORTFOLIO_RISK_ATTRIBUTION_ROLLING" / window_label / f"{as_of}.json"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _format_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def _dominant_regime(daily_summary: dict[str, Any]) -> tuple[str, int] | None:
    regime_counts = daily_summary.get("by_regime_code", {}) or {}
    if not regime_counts:
        return None
    items = sorted(
        ((str(code), int(count)) for code, count in regime_counts.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return items[0]


def _dominant_reason_codes_daily(
    daily_summary: dict[str, Any], *, limit: int = 3
) -> list[tuple[str, int]]:
    reason_counts = daily_summary.get("by_reason_code", {}) or {}
    items = sorted(
        ((str(code), int(count)) for code, count in reason_counts.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return items[:limit]


def _dominant_reason_codes_rolling(
    rolling_summary: dict[str, Any], *, limit: int = 3
) -> list[tuple[str, float, int]]:
    reason_totals = rolling_summary.get("breakdowns", {}).get("by_reason_code", {}) or {}
    items: list[tuple[str, float, int]] = []
    for code, payload in reason_totals.items():
        delta_notional = float(payload.get("delta_notional", 0.0))
        decisions = int(payload.get("decisions", 0))
        items.append((str(code), delta_notional, decisions))
    items.sort(key=lambda item: (-abs(item[1]), -item[2], item[0]))
    return items[:limit]


def _extract_daily_symbols(summary: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = summary.get("top_symbols_by_abs_delta_notional")
    if isinstance(candidates, list):
        return candidates
    candidates = summary.get("top_symbols_by_delta_notional")
    if isinstance(candidates, list):
        return candidates
    candidates = summary.get("top_symbols")
    if isinstance(candidates, list):
        return candidates
    return []


def _extract_rolling_symbols(summary: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = summary.get("top_symbols", {}).get("by_delta_notional")
    if isinstance(candidates, list):
        return candidates
    return []


def _sorted_daily_symbols(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not entries:
        return []
    enriched: list[dict[str, Any]] = []
    for entry in entries:
        symbol = str(entry.get("symbol") or "")
        if not symbol:
            continue
        delta_notional = float(entry.get("delta_notional", 0.0))
        abs_delta = entry.get("abs_delta_notional")
        if abs_delta is None:
            abs_delta = abs(delta_notional)
        enriched.append(
            {
                "symbol": symbol,
                "delta_notional": delta_notional,
                "abs_delta_notional": float(abs_delta),
            }
        )
    enriched.sort(key=lambda item: (-item["abs_delta_notional"], item["symbol"]))
    return enriched


def _sorted_rolling_symbols(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not entries:
        return []
    enriched: list[dict[str, Any]] = []
    for entry in entries:
        symbol = str(entry.get("symbol") or "")
        if not symbol:
            continue
        delta_notional = float(entry.get("delta_notional", 0.0))
        enriched.append({"symbol": symbol, "delta_notional": delta_notional})
    enriched.sort(key=lambda item: (item["delta_notional"], item["symbol"]))
    return enriched


def build_slack_summary(
    *,
    as_of: str,
    ledger_root: Path | str = Path("ledger"),
) -> str | None:
    ledger_root = Path(ledger_root)
    daily_path = resolve_daily_summary_path(as_of=as_of, ledger_root=ledger_root)
    if not daily_path.exists():
        return None

    daily_summary = _load_json(daily_path)
    rolling_summary = None
    rolling_path = resolve_rolling_summary_path(as_of=as_of, ledger_root=ledger_root)
    if rolling_path.exists():
        rolling_summary = _load_json(rolling_path)

    notional_totals = daily_summary.get("notional_totals", {}) or {}
    baseline_total = float(notional_totals.get("baseline_total", 0.0))
    modulated_total = float(notional_totals.get("modulated_total", 0.0))
    delta_total = float(notional_totals.get("delta_total", 0.0))
    delta_pct = None
    if baseline_total > 0:
        delta_pct = delta_total / baseline_total

    dominant_regime = _dominant_regime(daily_summary)

    reason_source = "daily"
    reason_lines: list[str] = []
    if rolling_summary is not None:
        reason_source = rolling_summary.get("window", {}).get("label", DEFAULT_WINDOW_LABEL)
        dominant_reasons = _dominant_reason_codes_rolling(rolling_summary)
        if dominant_reasons:
            reason_lines = [
                f"{code} ({_format_money(delta_notional)})"
                for code, delta_notional, _decisions in dominant_reasons
            ]
    else:
        dominant_reasons = _dominant_reason_codes_daily(daily_summary)
        if dominant_reasons:
            reason_lines = [f"{code} (count {count})" for code, count in dominant_reasons]

    daily_symbols = _sorted_daily_symbols(_extract_daily_symbols(daily_summary))
    affected_symbols_count = len(daily_symbols)

    top_symbols_source = None
    top_symbols_entries: list[dict[str, Any]] = []
    if rolling_summary is not None:
        top_symbols_source = reason_source
        top_symbols_entries = _sorted_rolling_symbols(
            _extract_rolling_symbols(rolling_summary)
        )
    else:
        top_symbols_source = "daily"
        top_symbols_entries = daily_symbols

    top_symbols_display = []
    for entry in top_symbols_entries[:3]:
        symbol = entry["symbol"]
        delta_notional = float(entry.get("delta_notional", 0.0))
        top_symbols_display.append(f"{symbol} ({_format_money(delta_notional)})")

    lines = [
        f"Risk attribution summary (shadow) — {as_of}",
        (
            "Exposure modulation (daily): "
            f"baseline {_format_money(baseline_total)}, "
            f"modulated {_format_money(modulated_total)}, "
            f"delta {_format_money(delta_total)} ({_format_pct(delta_pct)})."
        ),
    ]

    if dominant_regime is None:
        lines.append("Dominant regime (daily): none.")
    else:
        regime_code, regime_count = dominant_regime
        lines.append(
            f"Dominant regime (daily): {regime_code} (count {regime_count})."
        )

    if reason_lines:
        lines.append(
            f"Dominant reason codes ({reason_source}): {', '.join(reason_lines)}."
        )
    else:
        lines.append(f"Dominant reason codes ({reason_source}): none.")

    lines.append(f"Affected symbols (daily top list): {affected_symbols_count}.")

    if top_symbols_display:
        lines.append(
            f"Top symbols ({top_symbols_source}): {', '.join(top_symbols_display)}."
        )

    return "\n".join(lines)


def maybe_send_slack_summary(
    *,
    as_of: str,
    ledger_root: Path | str = Path("ledger"),
    slack_sender: Callable[..., None] | None = None,
) -> None:
    if not slack_summary_enabled():
        return
    if slack_sender is None:
        from alerts import slack

        slack_sender = slack.slack_alert
    try:
        message = build_slack_summary(as_of=as_of, ledger_root=ledger_root)
        if not message:
            return
        slack_sender(
            "INFO",
            "Risk attribution summary (shadow)",
            message,
            component="ANALYTICS",
        )
    except Exception as exc:  # noqa: BLE001 - fail-open
        print(f"WARN: risk attribution slack summary failed: {exc}")

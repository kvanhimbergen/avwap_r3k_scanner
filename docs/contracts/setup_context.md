# setup_context Contract (v1)

This document defines the canonical **Setup Context** output contract emitted by:

- `setup_context.compute_setup_context_contract(...)`

The contract is designed to label **context/state only** for candidates and must remain free of any execution intent.

---

## Purpose and Scope

**Setup Context provides:**
- Stable, versioned labels describing VWAP/AVWAP/extension/gap/structure context.
- Features and thresholds used to compute those labels.
- Deterministic provenance (rules hash + code version).
- A trace of which rule modules fired and what fields they produced.

**Setup Context explicitly excludes:**
- Entries, exits, stop placement, targets, position sizing, risk, PnL, expectancy, portfolio allocation, leverage.

This contract is a prerequisite for an execution wrapper that consumes setup state without recomputing context.

---

## Top-level Shape

A `setup_context` payload MUST have exactly these top-level keys:

- `schema`
- `identity`
- `provenance`
- `labels`
- `features`
- `trace`

---

## schema

```json
{
  "name": "setup_context",
  "version": 1
}
name is constant.

version increments only for breaking schema changes.

identity
json
Copy code
{
  "symbol": "AAPL",
  "scan_date": "2026-01-20",
  "timezone": "America/New_York",
  "session": "RTH"
}
symbol: non-empty string

scan_date: YYYY-MM-DD (date of the candidate / evaluation)

timezone: currently fixed to America/New_York

session: currently fixed to RTH

provenance
json
Copy code
{
  "setup_rules_version": 2,
  "setup_rules_hash": "sha256:<hex>",
  "code_version": "git:<sha>",
  "computed_at": "2026-01-20T02:34:02.357196+00:00",
  "data_window": {
    "daily_lookback_days": 120,
    "intraday_used": false,
    "intraday_granularity": null
  }
}
setup_rules_version: integer >= 2, from knowledge/rules/setup_rules.yaml

setup_rules_hash: sha256: prefix + hash of rule content (deterministic)

code_version: stable commit identifier (e.g., git:<sha>)

computed_at: ISO-8601 timestamp (timezone-aware recommended)

data_window:

daily_lookback_days: integer > 0

intraday_used: boolean (currently false)

intraday_granularity: string or null (must be null when intraday_used=false)

labels
labels.modules
Tracks module enablement state:

json
Copy code
{
  "vwap_context": "enabled",
  "avwap_context": "enabled",
  "extension_awareness": "enabled",
  "gap_context": "enabled",
  "structure_confirmation": "enabled"
}
Allowed values per module:

enabled

disabled

na

When a module is disabled, its downstream labels MUST be coerced to safe neutral values (see below).

labels.vwap
json
Copy code
{
  "control_label": "buyers_in_control",
  "control_relation": "above",
  "reclaim_acceptance_label": "accepted_above_vwap"
}
Enums:

control_label ∈ { "buyers_in_control", "sellers_in_control", "balanced_or_indecisive" }

control_relation ∈ { "above", "below", "around", "unknown" }

reclaim_acceptance_label ∈ { "below_vwap", "reclaiming_vwap", "accepted_above_vwap" }

Missing VWAP data MUST yield:

control_label = "balanced_or_indecisive"

control_relation = "unknown"

labels.avwap
AVWAP is represented per anchor-type with an optional key_anchor.

json
Copy code
{
  "per_anchor": {
    "major_high": {
      "state_label": "na",
      "relation": "unknown",
      "relevance": "unknown"
    },
    "major_low": {
      "state_label": "na",
      "relation": "unknown",
      "relevance": "unknown"
    }
  },
  "key_anchor": {
    "anchor_type": "major_high",
    "reason": "selected_anchor"
  }
}
Per-anchor enums:

state_label ∈ { "supply_overhead", "reclaiming_avwap", "demand_underfoot", "na" }

relation ∈ { "above", "below", "around", "unknown" }

relevance ∈ { "relevant", "far", "unknown" }

Notes:

If an unknown anchor_name is provided, per-anchor values MUST remain "na"/"unknown" and must not error.

If AVWAP module is enabled and anchor_name matches a known anchor type, key_anchor MUST be present and coherent.

labels.extension
json
Copy code
{
  "label": "moderately_extended",
  "reference": {
    "type": "vwap",
    "anchor_type": null
  }
}
Enums:

label ∈ { "compressed_near_value", "moderately_extended", "overextended_from_value", "na" }

reference.type ∈ { "vwap", "avwap" }

Consistency rule:

If labels.modules.avwap_context == "enabled", reference.type SHOULD be "avwap" when an AVWAP anchor is active.

When extension_awareness is disabled, labels.extension.label MUST be "na".

labels.gap
json
Copy code
{
  "has_gap": false,
  "direction": "none",
  "reset_reference_frame": true,
  "prioritize_post_gap_vwap": true,
  "allow_gap_day_anchor": true
}
has_gap: boolean

direction ∈ { "up", "down", "none" }

If has_gap == true, gap_pct MUST be present and be a float.

When gap_context is disabled:

has_gap MUST be false

direction MUST be "none"

labels.structure
json
Copy code
{
  "trend": "uptrend",
  "confirmation": "confirmed"
}
Enums:

trend ∈ { "uptrend", "downtrend", "range", "unknown" }

confirmation ∈ { "confirmed", "conflicted", "caution", "unknown" }

When structure_confirmation is disabled:

trend MUST be "unknown"

confirmation SHOULD be "unknown"

features
features is a flat dictionary of thresholds/parameters echoed from the rules/config used.

Examples (non-exhaustive; tests enforce key presence/behavior):

vwap_acceptance_days

gap_threshold_pct

structure_sma_fast

structure_sma_slow

structure_slope_lookback

extension_compressed_pct

extension_moderate_pct

extension_overextended_pct

All numeric values MUST be finite (no NaN/inf). Use null when unknown.

trace
trace is a list of module decisions. Each entry MUST be:

json
Copy code
{
  "rule_id": "vwap-context",
  "module": "vwap_context",
  "fired": true,
  "inputs": { "...": "..." },
  "outputs": [
    "labels.vwap.control_label",
    "labels.extension.label"
  ]
}
Rules:

trace MUST be a non-empty list when modules are enabled.

outputs are string paths referencing fields that exist in the context object.

rule_id MUST be stable non-empty string.

Forbidden-Key Policy
The setup context payload MUST NOT contain keys (case-insensitive substring match) that imply execution intent, including:

entry, entries, signal, order, buy, sell

stop, stop_loss, target, take_profit

position_size, sizing, risk, r_multiple, expectancy, pnl

portfolio, allocation, leverage

Versioning Policy
Additive changes that do not break consumers (new optional fields, new trace inputs) may remain under version: 1.

Any breaking change (renamed keys, enum changes, type changes) MUST increment schema.version.

Source of Truth
Contract validation is enforced by:

tests/test_setup_context_contract.py

If this document and tests diverge, tests are the enforcement gate and the document must be updated immediately.
MD

bash
Copy code

When you’ve run it, paste:

```bash
ls -la docs/contracts && git status
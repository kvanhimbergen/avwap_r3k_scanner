# Testing lanes

This repository supports two test lanes so Codex can run safely without heavy
dependencies while local/droplet environments can run the full suite.

## Unit lane (Codex/minimal deps)

Codex runs the unit lane to ensure safety-critical coverage without requiring
`pandas` or `numpy`. This lane always runs the Phase C gate test, and then runs
all tests that do not require those heavy dependencies:

```bash
./scripts/test_unit.sh
```

Equivalent commands:

```bash
pytest -q tests/test_execution_v2_live_gate.py
pytest -q -m "not requires_pandas and not requires_numpy"
```

## Full lane (local/droplet)

With full dependencies installed, run the entire suite:

```bash
./scripts/test_full.sh
```

Equivalent command:

```bash
pytest -q
```

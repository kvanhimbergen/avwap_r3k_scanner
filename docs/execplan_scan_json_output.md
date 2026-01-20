# Add JSON output support to the daily scan runner

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan follows the requirements in `docs/PLANS.md` and must be maintained accordingly.

## Purpose / Big Picture

The daily scan currently writes CSV output and a TradingView watchlist. After this change, an operator can run the scan with an explicit command-line flag that writes a JSON report containing both scan metadata and the full candidate list, making it possible to ingest the scan results into tools that expect structured JSON instead of CSV. Success is visible by running the scan command and seeing a JSON file created that lists the same number of candidates as the CSV output.

## Progress

- [x] (2026-01-20 00:00Z) Drafted the ExecPlan to add JSON output for scan results.
- [ ] Add JSON serialization helper for candidate DataFrames in `scan_engine.py`.
- [ ] Add CLI argument parsing to `run_scan.py` to enable JSON output and optional output path overrides.
- [ ] Validate the JSON output file contents and confirm tests run cleanly.

## Surprises & Discoveries

- Observation: None yet; this plan has not been implemented.
  Evidence: N/A.

## Decision Log

- Decision: Add JSON output through a new `scan_engine.write_candidates_json` helper and a `--output-json` flag in `run_scan.py` rather than modifying CSV output behavior.
  Rationale: This keeps the existing CSV workflow unchanged while providing an explicit opt-in for JSON output.
  Date/Author: 2026-01-20 / assistant.

## Outcomes & Retrospective

No implementation has been performed yet. The intended outcome is to make JSON output available alongside CSV output without changing existing behavior.

## Context and Orientation

The scan entrypoint is `run_scan.py`, which calls `scan_engine.run_scan(cfg)` to build a pandas `DataFrame` of candidate rows and then writes a CSV file via `scan_engine.write_candidates_csv`. The same script writes a TradingView watchlist file via `scan_engine.write_tradingview_watchlist`. The candidate data schema is controlled by `scan_engine.CANDIDATE_COLUMNS` and populated by `scan_engine.build_candidate_row`, which is used in `scan_engine.run_scan`. A JSON report should preserve the same candidate data but additionally include metadata such as scan date, candidate count, and output file path so a consumer can validate the scan in a single file.

Define terms used here in plain language. “Candidate rows” means the rows of the pandas `DataFrame` returned by `scan_engine.run_scan`, with columns listed in `scan_engine.CANDIDATE_COLUMNS`. “JSON report” means a UTF-8 encoded file containing a single JSON object with a `metadata` object and a `candidates` list of objects where each object corresponds to one candidate row.

## Plan of Work

First, add a JSON writer helper in `scan_engine.py` alongside `write_candidates_csv`. The function should accept the candidates DataFrame and a path, ensure the parent directory exists, and write a JSON object with two keys: `metadata` and `candidates`. `metadata` should include `schema_version` (hard-code 1 for now to match `SchemaVersion` in the data), `scan_date` (use the `ScanDate` value from the DataFrame if it exists, otherwise the current local date in `America/New_York`), `candidate_count` (length of the DataFrame), and `generated_at` (ISO 8601 timestamp in `America/New_York`). `candidates` should be a list of dicts produced by `df.to_dict(orient="records")` so all columns are included. Use `json.dump` with `indent=2` and `sort_keys=True` for stable output. If the DataFrame is empty, still emit the JSON object with an empty list.

Second, update `run_scan.py` to parse command-line arguments using `argparse`. Add a `--output-json` flag that, when provided, writes the JSON report in addition to the CSV output. Also add an optional `--output-json-path` argument that defaults to `daily_candidates.json` in the repository root. Preserve the current CSV output path behavior (`daily_candidates.csv`) so existing workflows are unaffected. When JSON output is written, print a message like `[json] wrote <count> candidates -> <path>` so operators can confirm success in the terminal.

Third, add documentation in `run_scan.py`’s module-level usage (comment or argparse description) explaining the new flag and the JSON report structure. Keep the explanation short and ensure it mentions `metadata` and `candidates` fields.

## Concrete Steps

Run all commands from the repository root (`/workspace/avwap_r3k_scanner`).

1. Edit `scan_engine.py` to add a new function `write_candidates_json` near `write_candidates_csv`.

   Expected new function signature and behavior:

       def write_candidates_json(df: pd.DataFrame, path: Path | str) -> None:
           """Write candidates to JSON with metadata."""
           # Ensure directory exists, build metadata, write JSON.

   Example terminal diff snippet (for orientation only):

       +def write_candidates_json(df: pd.DataFrame, path: Path | str) -> None:
       +    Path(path).parent.mkdir(parents=True, exist_ok=True)
       +    scan_date = ...
       +    payload = {"metadata": {...}, "candidates": df.to_dict(orient="records")}
       +    with open(path, "w", encoding="utf-8") as handle:
       +        json.dump(payload, handle, indent=2, sort_keys=True)

2. Edit `run_scan.py` to add argparse parsing at the top of `main()`.

   Use `argparse.ArgumentParser` with a short description. Add:

   - `--output-json` as a boolean flag to enable JSON output.
   - `--output-json-path` as an optional string path defaulting to `<repo_root>/daily_candidates.json`.

   After the CSV write, conditionally call `scan_engine.write_candidates_json(out, json_path)` when the flag is set, then print a confirmation line.

3. Update any usage/help text in `run_scan.py` so a novice understands the JSON file structure (metadata + candidates list).

## Validation and Acceptance

The change is accepted when a human can run the scan with JSON output and observe a valid JSON report. Use the following commands and verify the outputs.

1. Run the scan with JSON output enabled:

       cd /workspace/avwap_r3k_scanner
       python run_scan.py --output-json --output-json-path /tmp/daily_candidates.json

   Expected console output includes a line like:

       [json] wrote 20 candidates -> /tmp/daily_candidates.json

   (The number may vary; any integer count is acceptable.)

2. Verify the JSON structure by inspecting the file:

       python - <<'PY'
       import json
       from pathlib import Path
       data = json.loads(Path("/tmp/daily_candidates.json").read_text())
       assert "metadata" in data and "candidates" in data
       print("candidate_count", data["metadata"]["candidate_count"], "candidates", len(data["candidates"]))
       PY

   The printed counts should match. This confirms the JSON report is consistent.

3. Run the repository test suite to ensure no regressions:

       cd /workspace/avwap_r3k_scanner
       python tests/run_tests.py

   Expect all tests to pass; in particular, schema-related tests should still pass because the JSON output does not modify the existing CSV schema.

## Idempotence and Recovery

All steps are additive and can be re-run safely. If the JSON output is incorrect, delete the JSON file and re-run `python run_scan.py --output-json ...` after fixing the code. No migrations or irreversible operations are involved.

## Artifacts and Notes

Capture the JSON confirmation line and a short excerpt of the JSON file for evidence. For example:

    [json] wrote 20 candidates -> /tmp/daily_candidates.json

    {
      "metadata": {
        "candidate_count": 20,
        "generated_at": "2026-01-20T09:10:11-05:00",
        "scan_date": "2026-01-20",
        "schema_version": 1
      },
      "candidates": [
        {"SchemaVersion": 1, "ScanDate": "2026-01-20", "Symbol": "AAPL", ...}
      ]
    }

## Interfaces and Dependencies

The JSON output relies on Python’s standard `json` module and existing pandas DataFrame methods. Implement the following signature in `scan_engine.py`:

    def write_candidates_json(df: pd.DataFrame, path: Path | str) -> None:
        """Write the candidates DataFrame to JSON with metadata."""

The CLI interface is defined in `run_scan.py` using `argparse.ArgumentParser` and includes `--output-json` and `--output-json-path` options. Use `scan_engine.write_candidates_json` when the flag is set.

Plan update note: This ExecPlan was created on 2026-01-20 to add JSON output support for scan results, based on the current structure of `run_scan.py` and `scan_engine.py`.

/**
 * ReadinessCheck — inline strategy health diagnostic.
 * Shows state file status, last eval, allocations, ledger, warnings.
 */
import type { ReadinessStrategy } from "../types";

export function ReadinessCheck({ data }: { data: ReadinessStrategy | null }) {
  if (!data) {
    return <div className="text-tertiary" style={{ fontSize: "0.78rem" }}>No readiness data</div>;
  }

  const status = !data.state_file_exists
    ? "error"
    : data.warnings.length > 0
      ? "warn"
      : "ok";

  return (
    <div className={`readiness-card readiness-${status}`}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: "0.78rem" }}>
        <span>
          State File:{" "}
          <span className={data.state_file_exists ? "readiness-check" : "readiness-x"}>
            {data.state_file_exists ? "\u2713" : "\u2717"}
          </span>
        </span>
        <span>
          Last Eval:{" "}
          <span className="font-mono">{data.last_eval_date ?? "\u2014"}</span>
        </span>
        <span>
          Allocations:{" "}
          <span className="font-mono">
            {data.allocation_count} ({data.total_weight_pct.toFixed(0)}%)
          </span>
        </span>
        <span>
          Ledger Today:{" "}
          <span className="font-mono">{data.ledger_files_today} file{data.ledger_files_today !== 1 ? "s" : ""}</span>
        </span>
      </div>
      {data.warnings.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <span style={{ fontSize: "0.72rem", color: "var(--amber)", fontWeight: 600 }}>Warnings:</span>
          <ul className="warning-list">
            {data.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

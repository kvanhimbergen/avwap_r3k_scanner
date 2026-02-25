/**
 * ReadinessCheck — inline strategy health diagnostic.
 * Shows state file status, last eval, allocations, ledger, warnings.
 */
import type { ReadinessStrategy } from "../types";
import { Check, X } from "../icons";

const WARNING_LABELS: Record<string, string> = {
  stale_portfolio_snapshot: "Portfolio snapshot is stale",
  no_portfolio_snapshot: "No portfolio snapshot found",
  stale_eval: "Evaluation is stale (not run today)",
  no_allocations: "No allocations recorded",
  missing_state_file: "State file missing",
  state_file_corrupt: "State file is corrupt",
};

function warningLabel(code: string): string {
  return WARNING_LABELS[code] ?? code;
}

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
        {data.book_id && (
          <span>
            Book:{" "}
            <span className={`book-badge ${data.book_id === "ALPACA_PAPER" ? "alpaca" : "schwab"}`}>
              {data.book_id === "ALPACA_PAPER" ? "ALP" : "SCH"}
            </span>
          </span>
        )}
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          State File:{" "}
          <span className={data.state_file_exists ? "readiness-check" : "readiness-x"}>
            {data.state_file_exists
              ? <Check size={14} strokeWidth={2.5} />
              : <X size={14} strokeWidth={2.5} />
            }
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
          <span className="font-mono">{data.today_ledger_count} file{data.today_ledger_count !== 1 ? "s" : ""}</span>
        </span>
      </div>
      {data.warnings.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <span style={{ fontSize: "0.72rem", color: "var(--amber)", fontWeight: 600 }}>Warnings:</span>
          <ul className="warning-list">
            {data.warnings.map((w, i) => (
              <li key={i}>{warningLabel(w)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

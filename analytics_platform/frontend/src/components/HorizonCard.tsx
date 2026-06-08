import { formatCurrency, formatPercent } from "../lib/format";
import type { HorizonProjection } from "../types";

interface HorizonCardProps {
  data?: HorizonProjection | null;
  className?: string;
}

const VERDICT_STYLES: Record<string, string> = {
  "ON TRACK": "bg-vantage-green/15 text-vantage-green",
  AHEAD: "bg-vantage-green/15 text-vantage-green",
  BEHIND: "bg-vantage-amber/15 text-vantage-amber",
};

/**
 * Anchors the dashboard in destination terms: years to retirement, current
 * balance, projected at 65, goal, and an on-track verdict. Replaces the
 * "Account Value" stat as the page-opening framing for a 51yo investor whose
 * primary question at 6am is "am I still on track."
 */
export function HorizonCard({ data, className }: HorizonCardProps) {
  const containerClass = `bg-vantage-card border border-vantage-border rounded-lg p-4 ${className ?? ""}`;

  if (!data) {
    return (
      <div className={containerClass}>
        <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Horizon</p>
        <p className="text-xs text-vantage-muted">Projection unavailable.</p>
      </div>
    );
  }

  const verdictClass = data.verdict ? VERDICT_STYLES[data.verdict] ?? "" : "";

  return (
    <div className={containerClass}>
      <div className="flex items-baseline justify-between mb-3">
        <p className="text-[11px] text-vantage-muted uppercase tracking-wide">Horizon</p>
        <p className="text-[10px] text-vantage-muted">
          {data.years_to_retirement} years to retirement at {data.retirement_age}
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Now</p>
          <p className="font-mono text-xl font-bold text-vantage-text">
            {formatCurrency(data.current_balance, 0)}
          </p>
          {data.as_of_date && (
            <p className="text-[10px] text-vantage-muted mt-0.5">as of {data.as_of_date}</p>
          )}
        </div>

        <div>
          <p className="text-[10px] text-vantage-muted uppercase tracking-wide">
            At {data.retirement_age}
          </p>
          <p className="font-mono text-xl font-bold text-vantage-text">
            {data.projected_at_retirement != null
              ? formatCurrency(data.projected_at_retirement, 0)
              : "—"}
          </p>
          {data.trailing_cagr != null && (
            <p className="text-[10px] text-vantage-muted mt-0.5">
              at {formatPercent(data.trailing_cagr * 100)} CAGR
            </p>
          )}
        </div>

        <div>
          <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Goal</p>
          <p className="font-mono text-xl font-bold text-vantage-text">
            {formatCurrency(data.goal_balance, 0)}
          </p>
          {data.goal_pct != null && (
            <p className="text-[10px] text-vantage-muted mt-0.5">
              projection = {(data.goal_pct * 100).toFixed(0)}% of goal
            </p>
          )}
        </div>
      </div>

      {data.verdict && (
        <div className="mt-3 pt-3 border-t border-vantage-border">
          <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wide ${verdictClass}`}>
            {data.verdict}
          </span>
        </div>
      )}
    </div>
  );
}

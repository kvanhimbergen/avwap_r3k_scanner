import { getMeta } from "../lib/strategies";
import type { SleeveDDRow, SubStrategyDD } from "../types";

interface SleeveHealthTableProps {
  data?: SubStrategyDD | null;
  warnThreshold?: number;   // e.g. -0.10 → amber
  alertThreshold?: number;  // e.g. -0.15 → red
  className?: string;
}

function ddCellClass(dd: number, warn: number, alert: number): string {
  if (dd <= alert) return "text-vantage-red font-semibold";
  if (dd <= warn) return "text-vantage-amber font-semibold";
  return "text-vantage-text";
}

function rowBgClass(dd: number, warn: number, alert: number): string {
  if (dd <= alert) return "bg-vantage-red/[0.06]";
  if (dd <= warn) return "bg-vantage-amber/[0.06]";
  return "";
}

function sleeveDisplay(key: string): { short: string; color: string } {
  // The DD report uses lowercase keys ('v3', 'v4', 'v5'); strategy meta is
  // keyed by RAEC_401K_V3 etc.
  const sid = `RAEC_401K_${key.toUpperCase()}`;
  try {
    const meta = getMeta(sid);
    return { short: meta.shortName, color: meta.color };
  } catch {
    return { short: key.toUpperCase(), color: "#9ca3af" };
  }
}

/**
 * Per-sleeve drawdown health — the dashboard manifestation of
 * `analytics/strategy_dd_report.py`. Highlights any sleeve over the warn
 * or alert threshold so a 51yo investor can see which sub-strategy is
 * bleeding without parsing a P&L sheet.
 */
export function SleeveHealthTable({
  data,
  warnThreshold = -0.10,
  alertThreshold = -0.15,
  className,
}: SleeveHealthTableProps) {
  const containerClass = `bg-vantage-card border border-vantage-border rounded-lg p-4 ${className ?? ""}`;

  if (!data || data.sleeves.length === 0) {
    return (
      <div className={containerClass}>
        <h3 className="text-sm font-semibold mb-2">Per-sleeve health</h3>
        <p className="text-xs text-vantage-muted">
          {data?.error ?? "No coordinator runs found — sleeve DD will populate after the next pipeline run."}
        </p>
      </div>
    );
  }

  return (
    <div className={containerClass}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold">Per-sleeve health</h3>
        <p className="text-[10px] text-vantage-muted">
          warn {(warnThreshold * 100).toFixed(0)}% · alert {(alertThreshold * 100).toFixed(0)}%
        </p>
      </div>

      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-vantage-border">
            <th className="py-2 px-2 text-left text-vantage-muted font-medium">Sleeve</th>
            <th className="py-2 px-2 text-right text-vantage-muted font-medium">Alloc</th>
            <th className="py-2 px-2 text-right text-vantage-muted font-medium">Equity</th>
            <th className="py-2 px-2 text-right text-vantage-muted font-medium">DD vs peak</th>
            <th className="py-2 px-2 text-right text-vantage-muted font-medium">Max DD</th>
            <th className="py-2 px-2 text-right text-vantage-muted font-medium">Contrib book DD</th>
          </tr>
        </thead>
        <tbody>
          {data.sleeves.map((row: SleeveDDRow) => {
            const meta = sleeveDisplay(row.key);
            const bg = rowBgClass(row.current_dd, warnThreshold, alertThreshold);
            return (
              <tr key={row.key} className={`border-b border-vantage-border/50 ${bg}`}>
                <td className="py-2 px-2 font-mono font-semibold">
                  <span className="inline-flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full inline-block"
                      style={{ backgroundColor: meta.color }}
                    />
                    {meta.short}
                  </span>
                </td>
                <td className="py-2 px-2 font-mono text-right text-vantage-muted">
                  {row.allocation_pct.toFixed(0)}%
                </td>
                <td className="py-2 px-2 font-mono text-right">
                  {row.final_equity.toFixed(3)}
                </td>
                <td className={`py-2 px-2 font-mono text-right ${ddCellClass(row.current_dd, warnThreshold, alertThreshold)}`}>
                  {(row.current_dd * 100).toFixed(1)}%
                </td>
                <td className={`py-2 px-2 font-mono text-right ${ddCellClass(row.max_dd, warnThreshold, alertThreshold)}`}>
                  {(row.max_dd * 100).toFixed(1)}%
                  {row.max_dd_date && (
                    <span className="text-[10px] text-vantage-muted ml-1">{row.max_dd_date}</span>
                  )}
                </td>
                <td className="py-2 px-2 font-mono text-right text-vantage-muted">
                  {(row.contribution_to_book_max_dd * 100).toFixed(2)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {data.book_max_dd_contribution_sum < 0 && (
        <p className="text-[10px] text-vantage-muted mt-3">
          Sum of sleeve contributions to book max DD:{" "}
          <span className="font-mono">
            {(data.book_max_dd_contribution_sum * 100).toFixed(2)}%
          </span>{" "}
          (= Σ alloc × sleeve max DD)
        </p>
      )}
    </div>
  );
}

import { RegimeBadge } from "./Badge";
import type { RegimeNarrative } from "../types";

interface TodayStateCardProps {
  data?: RegimeNarrative | null;
  className?: string;
}

/**
 * "What is the system doing today and why?" — the narrative companion to the
 * regime/hedge/leveraged-cap state. The point of this card is that a 51yo
 * investor opening the dashboard at 6am should immediately see whether the
 * machinery is at rest (RISK_ON, hedge dormant, leveraged room available) or
 * actively defending (RISK_OFF, hedge active, cap binding), with a one-line
 * "why" rather than a metric they have to decode.
 */
export function TodayStateCard({ data, className }: TodayStateCardProps) {
  const containerClass = `bg-vantage-card border border-vantage-border rounded-lg p-4 ${className ?? ""}`;

  if (!data || data.regime == null) {
    return (
      <div className={containerClass}>
        <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-2">Today</p>
        <p className="text-xs text-vantage-muted">Regime state unavailable.</p>
      </div>
    );
  }

  const leverageRatio = data.leveraged_cap_pct > 0 ? data.leveraged_used_pct / data.leveraged_cap_pct : 0;
  const leverageColor = leverageRatio >= 0.95
    ? "text-vantage-amber"
    : leverageRatio >= 0.5
      ? "text-vantage-text"
      : "text-vantage-muted";

  const hedgeColor = data.hedge_state === "active" ? "text-vantage-amber" : "text-vantage-muted";

  return (
    <div className={containerClass}>
      <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-2">Today</p>

      <div className="space-y-2">
        {/* Regime + days held */}
        <div className="flex items-baseline gap-2">
          <RegimeBadge regime={data.regime} />
          <span className="font-mono text-xs text-vantage-muted">
            {data.days_in_regime} {data.days_in_regime === 1 ? "day" : "days"}
          </span>
        </div>

        {/* Hedge state */}
        <div className="flex items-baseline gap-2 text-xs">
          <span className="text-vantage-muted uppercase tracking-wide text-[10px] w-14">Hedge</span>
          <span className={`font-mono font-semibold ${hedgeColor}`}>
            {data.hedge_state}
          </span>
          {data.hedge_state === "active" && data.hedge_pct_of_book > 0 && (
            <span className="font-mono text-vantage-muted">
              ({data.hedge_pct_of_book.toFixed(1)}% of book)
            </span>
          )}
        </div>

        {/* Leveraged cap utilization */}
        <div className="flex items-baseline gap-2 text-xs">
          <span className="text-vantage-muted uppercase tracking-wide text-[10px] w-14">Lev cap</span>
          <span className={`font-mono font-semibold ${leverageColor}`}>
            {data.leveraged_used_pct.toFixed(1)}% / {data.leveraged_cap_pct.toFixed(0)}%
          </span>
        </div>

        {/* One-line why */}
        {data.reason && (
          <p className="text-[11px] text-vantage-muted leading-relaxed pt-2 border-t border-vantage-border/60">
            {data.reason}
          </p>
        )}
      </div>
    </div>
  );
}

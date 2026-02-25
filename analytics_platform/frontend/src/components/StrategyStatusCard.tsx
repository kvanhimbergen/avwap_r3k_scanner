/**
 * Compact strategy card for the Command Center grid.
 * Shows status dot, name, regime badge (inline), sparkline, and key metric.
 */
import { useNavigate } from "react-router-dom";

import { BookBadge } from "./BookBadge";
import { RegimeBadge } from "./RegimeBadge";
import { Sparkline } from "./Sparkline";
import { StatusDot, type StatusLevel } from "./StatusDot";

export interface StrategyCardData {
  strategyId: string;
  shortName: string;
  subtitle: string;
  regime: string | null;
  health: StatusLevel;
  sparklineData: number[];
  metricLabel: string;
  metricValue: string | number;
}

export function StrategyStatusCard({ data }: { data: StrategyCardData }) {
  const navigate = useNavigate();

  const healthClass =
    data.health === "error" ? "error" : data.health === "warn" ? "warn" : "";

  return (
    <div
      className={`strategy-card ${healthClass}`}
      onClick={() => navigate(`/strategies/${encodeURIComponent(data.strategyId)}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigate(`/strategies/${encodeURIComponent(data.strategyId)}`);
        }
      }}
    >
      <div className="strategy-card-header">
        <span className="strategy-card-name">
          <StatusDot status={data.health} />
          {data.shortName}
          <RegimeBadge regime={data.regime} />
        </span>
        <BookBadge strategyId={data.strategyId} />
      </div>
      <div className="strategy-card-subtitle">{data.subtitle}</div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <Sparkline data={data.sparklineData} width={54} height={18} />
        <span className="strategy-card-metric">
          <span className="font-bold">{data.metricValue}</span> {data.metricLabel}
        </span>
      </div>
    </div>
  );
}

/**
 * StrategyRosterCard — larger detail card for the strategy roster.
 * Shows more data than StrategyStatusCard: trades, exposure, sparkline, regime.
 */
import { useNavigate } from "react-router-dom";

import { RegimeBadge } from "./RegimeBadge";
import { Sparkline } from "./Sparkline";
import { StatusDot, type StatusLevel } from "./StatusDot";

export interface RosterCardData {
  strategyId: string;
  shortName: string;
  subtitle: string;
  regime: string | null;
  health: StatusLevel;
  sparklineData: number[];
  trades: number;
  uniqueSymbols: number;
  exposure?: string;
  dayPnl?: string;
  slippage?: string;
  rebalances?: number;
  lastEval?: string;
  isCompact?: boolean;
}

export function StrategyRosterCard({ data }: { data: RosterCardData }) {
  const navigate = useNavigate();
  const healthClass = data.health === "error" ? "error" : data.health === "warn" ? "warn" : "";

  if (data.isCompact) {
    return (
      <div
        className={`roster-card roster-card-compact ${healthClass}`}
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
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
          <StatusDot status={data.health} />
          <span className="font-bold" style={{ fontSize: "0.82rem" }}>{data.shortName}</span>
          <span className="text-tertiary" style={{ fontSize: "0.68rem" }}>{data.subtitle}</span>
        </div>
        <RegimeBadge regime={data.regime} />
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginTop: 6 }}>
          <Sparkline data={data.sparklineData} width={48} height={16} />
          <span className="font-mono text-secondary" style={{ fontSize: "0.72rem" }}>
            {data.rebalances ?? data.trades} {data.rebalances != null ? "reb" : "trd"}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`roster-card ${healthClass}`}
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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <StatusDot status={data.health} />
          <span className="font-bold" style={{ fontSize: "0.88rem" }}>{data.shortName}</span>
          <span className="text-tertiary" style={{ fontSize: "0.72rem" }}>{data.subtitle}</span>
        </div>
        <RegimeBadge regime={data.regime} />
      </div>

      <div className="roster-card-stats">
        <div className="roster-card-stat">
          <span className="roster-card-stat-label">Trades</span>
          <span className="roster-card-stat-value">{data.trades}</span>
        </div>
        <div className="roster-card-stat">
          <span className="roster-card-stat-label">Symbols</span>
          <span className="roster-card-stat-value">{data.uniqueSymbols}</span>
        </div>
        {data.exposure && (
          <div className="roster-card-stat">
            <span className="roster-card-stat-label">Exposure</span>
            <span className="roster-card-stat-value">{data.exposure}</span>
          </div>
        )}
        {data.dayPnl && (
          <div className="roster-card-stat">
            <span className="roster-card-stat-label">Day P&L</span>
            <span className="roster-card-stat-value">{data.dayPnl}</span>
          </div>
        )}
        {data.slippage && (
          <div className="roster-card-stat">
            <span className="roster-card-stat-label">Slippage</span>
            <span className="roster-card-stat-value">{data.slippage}</span>
          </div>
        )}
        {data.rebalances != null && (
          <div className="roster-card-stat">
            <span className="roster-card-stat-label">Rebalances</span>
            <span className="roster-card-stat-value">{data.rebalances}</span>
          </div>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 8 }}>
        <Sparkline data={data.sparklineData} width={80} height={20} />
        <span style={{ fontSize: "0.72rem", color: "var(--accent)" }}>View Tearsheet \u2192</span>
      </div>
    </div>
  );
}

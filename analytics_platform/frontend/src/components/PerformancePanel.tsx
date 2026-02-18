/**
 * PerformancePanel — KPI strip + performance summary for a strategy.
 * Shows rebalances, regime changes, avg drift, events.
 */
import { KpiCard } from "./KpiCard";

export interface PerformanceData {
  rebalances: number;
  regimeChanges: number;
  avgDrift: number | null;
  events: number;
  trades?: number;
  uniqueSymbols?: number;
}

export function PerformancePanel({ data }: { data: PerformanceData }) {
  return (
    <div>
      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))" }}>
        {data.trades != null && (
          <KpiCard label="Trades" value={data.trades} />
        )}
        <KpiCard label="Rebalances" value={data.rebalances} />
        <KpiCard label="Regime Changes" value={data.regimeChanges} />
        <KpiCard
          label="Avg Drift"
          value={data.avgDrift != null ? `${data.avgDrift.toFixed(1)}%` : "\u2014"}
        />
        <KpiCard label="Events" value={data.events} />
        {data.uniqueSymbols != null && (
          <KpiCard label="Symbols" value={data.uniqueSymbols} />
        )}
      </div>
    </div>
  );
}

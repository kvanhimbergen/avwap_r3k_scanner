import { useState } from "react";
import { Bar, BarChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

const STRATEGIES = [
  { id: "", label: "All Strategies" },
  { id: "RAEC_401K_V1", label: "V1 — Core" },
  { id: "RAEC_401K_V2", label: "V2 — Enhanced" },
  { id: "RAEC_401K_V3", label: "V3 — Aggressive" },
  { id: "RAEC_401K_V4", label: "V4 — Global Macro" },
  { id: "RAEC_401K_V5", label: "V5 — AI/Tech" },
  { id: "RAEC_401K_COORD", label: "Coordinator" },
];

export function PnlPage() {
  const [strategyId, setStrategyId] = useState("");
  const pnl = usePolling(() => api.pnl({ strategy_id: strategyId || undefined }), 45_000);

  if (pnl.loading) return <LoadingState text="Loading P&L data..." />;
  if (pnl.error) return <ErrorState error={pnl.error} />;

  const data = (pnl.data?.data as Record<string, any>) ?? {};
  const byStrategy: any[] = data.by_strategy ?? [];
  const allocationDrift: any[] = data.allocation_drift ?? [];

  const totalRebalances = byStrategy.reduce((sum, s) => sum + (s.rebalance_count ?? 0), 0);
  const totalRegimeChanges = byStrategy.reduce((sum, s) => sum + (s.regime_changes ?? 0), 0);

  return (
    <section>
      <h2 className="page-title">P&L &amp; Drift Analysis</h2>

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          Track <strong>rebalance frequency</strong> and <strong>regime changes</strong> across strategies.
          The drift chart shows the gap between target and current allocations over time — large or
          persistent drift may indicate execution delays or liquidity issues.
        </p>
      </div>

      <div className="filter-bar">
        <label>
          Strategy:{" "}
          <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
            {STRATEGIES.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Rebalance Count" value={totalRebalances} />
        <KpiCard label="Regime Changes" value={totalRegimeChanges} />
        <KpiCard label="Strategies With Data" value={byStrategy.length} />
      </div>

      {/* Allocation drift chart */}
      {allocationDrift.length > 0 && (
        <div className="chart-card">
          <h3>Allocation Drift Over Time</h3>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={allocationDrift}>
              <XAxis dataKey="ny_date" />
              <YAxis unit="%" />
              <Tooltip />
              <Line type="monotone" dataKey="drift" stroke="#dd6b20" strokeWidth={2} dot={false} name="Drift %" />
              <Line
                type="monotone"
                dataKey="target_total"
                stroke="#0f9d58"
                strokeWidth={1.5}
                dot={false}
                name="Target %"
              />
              <Line
                type="monotone"
                dataKey="current_total"
                stroke="#1f6feb"
                strokeWidth={1.5}
                dot={false}
                name="Current %"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Rebalance frequency by strategy */}
      {byStrategy.length > 0 && (
        <div className="chart-card">
          <h3>Rebalance Frequency by Strategy</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={byStrategy}>
              <XAxis dataKey="strategy_id" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="rebalance_count" fill="#1f6feb" name="Rebalances" />
              <Bar dataKey="regime_changes" fill="#dd6b20" name="Regime Changes" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

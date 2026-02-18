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

export function RaecDashboardPage() {
  const [strategyId, setStrategyId] = useState("");
  const dashboard = usePolling(
    () => api.raecDashboard({ strategy_id: strategyId || undefined }),
    45_000,
  );

  if (dashboard.loading) return <LoadingState text="Loading RAEC dashboard..." />;
  if (dashboard.error) return <ErrorState error={dashboard.error} />;

  const data = dashboard.data?.data as Record<string, any> ?? {};
  const summary = data.summary ?? {};
  const byStrategy = summary.by_strategy ?? [];
  const regimeHistory = data.regime_history ?? [];
  const allocations = data.allocation_snapshots ?? [];

  return (
    <section>
      <h2 className="page-title">RAEC 401(k) Dashboard</h2>

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          This page shows the status of all RAEC 401(k) rotation strategies.
          Monitor <strong>regime transitions</strong> and <strong>rebalance frequency</strong> to ensure
          strategies are responding to market conditions. Check target allocations to verify
          position sizing aligns with risk parameters.
        </p>
      </div>

      <div className="filter-bar">
        <label>
          Strategy:{" "}
          <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
            {STRATEGIES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Total Events" value={summary.total_rebalance_events ?? 0} />
        <KpiCard label="Rebalances Triggered" value={summary.rebalances_triggered ?? 0} />
        <KpiCard label="Active Strategies" value={byStrategy.length} />
      </div>

      {/* Strategy summary table */}
      <div className="table-card">
        <h3>Strategy Status</h3>
        <table>
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Events</th>
              <th>Rebalances</th>
              <th>Regime</th>
              <th>Last Eval</th>
              <th>Vol Target</th>
            </tr>
          </thead>
          <tbody>
            {byStrategy.map((s: any) => (
              <tr key={s.strategy_id}>
                <td>{s.strategy_id}</td>
                <td>{s.events}</td>
                <td>{s.rebalances}</td>
                <td><span className={`regime-badge ${s.current_regime?.toLowerCase().replace("_", "-") ?? ""}`}>{s.current_regime ?? "—"}</span></td>
                <td>{s.last_eval_date ?? "—"}</td>
                <td>{s.portfolio_vol_target != null ? `${(s.portfolio_vol_target * 100).toFixed(0)}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Regime history chart */}
      {regimeHistory.length > 0 && (
        <div className="chart-card">
          <h3>Regime Timeline</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={regimeHistory}>
              <XAxis dataKey="ny_date" />
              <YAxis />
              <Tooltip />
              <Line type="stepAfter" dataKey="regime" stroke="#1f6feb" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Allocation bar chart */}
      {allocations.length > 0 && (
        <div className="chart-card">
          <h3>Current Target Allocations</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={allocations.filter((a: any) => a.alloc_type === "target")}>
              <XAxis dataKey="symbol" />
              <YAxis unit="%" />
              <Tooltip />
              <Bar dataKey="weight_pct" fill="#1f6feb" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { FreshnessBanner } from "../components/FreshnessBanner";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";
import type { FreshnessRow, TimePoint } from "../types";

export function OverviewPage() {
  const overview = usePolling(() => api.overview(), 45_000);
  const timeseries = usePolling(() => api.decisionsTimeseries(), 45_000);
  const freshness = usePolling(() => api.freshness(), 60_000);
  const raec = usePolling(() => api.raecDashboard(), 45_000);

  if (overview.loading || timeseries.loading || freshness.loading) {
    return <LoadingState text="Loading overview..." />;
  }
  if (overview.error) return <ErrorState error={overview.error} />;
  if (timeseries.error) return <ErrorState error={timeseries.error} />;
  if (freshness.error) return <ErrorState error={freshness.error} />;

  const totals = (overview.data?.data.totals ?? {}) as Record<string, number>;
  const points = (timeseries.data?.data.points ?? []) as TimePoint[];
  const freshnessRows = (freshness.data?.data.rows ?? []) as FreshnessRow[];

  return (
    <section>
      <h2 className="page-title">Overview</h2>
      <FreshnessBanner rows={freshnessRows} />
      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          Use this page as the daily pulse check. Rising <strong>accepted</strong> with stable{" "}
          <strong>gate blocks</strong> usually means execution flow is healthy. If <strong>rejected</strong> or{" "}
          <strong>gate blocks</strong> spike versus recent days, drill into Decisions and S2 Signals to find the
          dominant reason codes and symbols.
        </p>
      </div>
      <div className="kpi-grid">
        <KpiCard label="Decision Cycles" value={totals.cycle_count ?? 0} />
        <KpiCard label="Intent Rows" value={totals.intent_count ?? 0} />
        <KpiCard label="Accepted" value={totals.accepted_count ?? 0} />
        <KpiCard label="Rejected" value={totals.rejected_count ?? 0} />
        <KpiCard label="Gate Blocks" value={totals.gate_block_count ?? 0} />
        <KpiCard label="Created Intents" value={totals.created_count ?? 0} />
      </div>
      <div className="chart-card">
        <h3>Decision + Rejection Trend</h3>
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={points}>
            <XAxis dataKey="ny_date" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="cycle_count" stroke="#1f6feb" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="rejected_count" stroke="#dd6b20" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="accepted_count" stroke="#0f9d58" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {raec.data && !raec.error && (
        <div className="table-card">
          <h3>RAEC 401(k) Status</h3>
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Regime</th>
                <th>Last Eval</th>
                <th>Rebalances</th>
              </tr>
            </thead>
            <tbody>
              {((raec.data.data as any)?.summary?.by_strategy ?? []).map((s: any) => (
                <tr key={s.strategy_id}>
                  <td>{s.strategy_id}</td>
                  <td>
                    <span className={`regime-badge ${s.current_regime?.toLowerCase().replace("_", "-") ?? ""}`}>
                      {s.current_regime ?? "—"}
                    </span>
                  </td>
                  <td>{s.last_eval_date ?? "—"}</td>
                  <td>{s.rebalances ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

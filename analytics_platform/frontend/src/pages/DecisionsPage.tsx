import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";
import type { TimePoint } from "../types";

export function DecisionsPage() {
  const timeseries = usePolling(() => api.decisionsTimeseries(), 45_000);

  if (timeseries.loading) return <LoadingState text="Loading decision diagnostics..." />;
  if (timeseries.error) return <ErrorState error={timeseries.error} />;

  const points = (timeseries.data?.data.points ?? []) as TimePoint[];

  return (
    <section>
      <h2 className="page-title">Decision Diagnostics</h2>
      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          This chart shows operational friction. <strong>Cycle count</strong> should be stable for your runtime cadence.
          If <strong>rejected_count</strong> rises while cycles are steady, check rejection reasons for data/quality
          issues. If <strong>gate_blocks</strong> jump, prioritize market/freshness/risk gate diagnostics before tuning
          strategy logic.
        </p>
      </div>
      <div className="chart-card">
        <h3>Daily Decision / Gate / Rejection</h3>
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={points}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="ny_date" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="cycle_count" fill="#1f6feb" />
            <Bar dataKey="rejected_count" fill="#dd6b20" />
            <Bar dataKey="gate_blocks" fill="#111111" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

import { useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

export function BacktestsPage() {
  const runs = usePolling(() => api.backtestRuns(), 90_000);
  const [selectedRun, setSelectedRun] = useState<string>("");
  const detail = usePolling(
    () => (selectedRun ? api.backtestRun(selectedRun) : Promise.resolve(null as never)),
    90_000
  );

  useEffect(() => {
    const rows = (runs.data?.data.runs ?? []) as Array<Record<string, unknown>>;
    if (!selectedRun && rows.length > 0) {
      setSelectedRun(String(rows[0].run_id));
    }
  }, [runs.data, selectedRun]);

  if (runs.loading) return <LoadingState text="Loading backtest runs..." />;
  if (runs.error) return <ErrorState error={runs.error} />;

  const runRows = (runs.data?.data.runs ?? []) as Array<Record<string, unknown>>;
  const metrics = (detail.data?.data.metrics ?? []) as Array<Record<string, unknown>>;
  const equity = (detail.data?.data.equity_curve ?? []) as Array<Record<string, unknown>>;

  return (
    <section>
      <h2 className="page-title">Backtests & Replay</h2>
      <p className="page-subtitle">Historical strategy replay and equity curve analysis</p>
      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          Use this page to compare scenario stability, not single-run wins. Favor runs with consistent equity slope and
          controlled drawdown metrics over high-return outliers. If a parameter set looks strong here but weak in live
          diagnostics, treat it as overfit risk and re-test with broader windows.
        </p>
      </div>
      <div className="filter-row">
        <label>
          Run
          <select value={selectedRun} onChange={(event) => setSelectedRun(event.target.value)}>
            {runRows.map((row) => (
              <option key={String(row.run_id)} value={String(row.run_id)}>
                {String(row.suite)} / {String(row.variant)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {detail.loading ? <LoadingState text="Loading run detail..." /> : null}
      {detail.error ? <ErrorState error={detail.error} /> : null}

      <div className="two-col">
        <div className="table-card">
          <h3>Metrics</h3>
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((metric) => (
                <tr key={String(metric.metric_name)}>
                  <td>{String(metric.metric_name)}</td>
                  <td>{String(metric.metric_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="chart-card">
          <h3>Equity Curve</h3>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={equity}>
              <XAxis dataKey="x_value" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="equity" stroke="var(--green)" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  );
}

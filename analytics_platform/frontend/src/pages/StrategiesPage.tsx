import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

export function StrategiesPage() {
  const compare = usePolling(() => api.strategiesCompare(), 45_000);

  if (compare.loading) return <LoadingState text="Loading strategy compare..." />;
  if (compare.error) return <ErrorState error={compare.error} />;

  const intentRows = (compare.data?.data.intent_compare ?? []) as Array<Record<string, unknown>>;
  const reasonRows = (compare.data?.data.s2_reason_mix ?? []) as Array<Record<string, unknown>>;

  return (
    <section>
      <h2 className="page-title">Strategy Compare</h2>
      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          Compare strategy throughput and concentration. A single strategy dominating <strong>intent rows</strong> or
          collapsing to very few <strong>unique symbols</strong> may indicate over-concentration. In the S2 reason mix,
          watch for repeated blockers (for example trend/momentum failures) to tune filters without changing AVWAP.
        </p>
      </div>
      <div className="chart-card">
        <h3>Intent Rows by Strategy</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={intentRows}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="strategy_id" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="intent_rows" fill="#1f6feb" />
            <Bar dataKey="unique_symbols" fill="#0f9d58" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="table-card">
        <h3>S2 Reason Mix</h3>
        <table>
          <thead>
            <tr>
              <th>Reason</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody>
            {reasonRows.map((row) => (
              <tr key={`${row.reason_code}`}>
                <td>{String(row.reason_code ?? "")}</td>
                <td>{String(row.reason_count ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

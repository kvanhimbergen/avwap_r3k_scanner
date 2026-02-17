import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

export function RiskPage() {
  const risk = usePolling(() => api.riskControls(), 60_000);

  if (risk.loading) return <LoadingState text="Loading risk controls..." />;
  if (risk.error) return <ErrorState error={risk.error} />;

  const controls = (risk.data?.data.risk_controls ?? []) as Array<Record<string, unknown>>;
  const regimes = (risk.data?.data.regimes ?? []) as Array<Record<string, unknown>>;

  return (
    <section>
      <h2 className="page-title">Risk Controls & Regime</h2>
      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          Treat this page as your guardrail monitor. Falling <strong>risk_multiplier</strong> or tighter caps indicate
          portfolio throttling. Regime shifts explain why sizing pressure changes day to day. Persistent throttling may
          justify reducing aggression or tightening candidate quality until conditions improve.
        </p>
      </div>
      <div className="two-col">
        <div className="table-card">
          <h3>Risk Control Events</h3>
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Source</th>
                <th>Risk Mult.</th>
                <th>Max Pos.</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {controls.map((row, idx) => (
                <tr key={`${row.source_type}-${row.as_of_utc}-${idx}`}>
                  <td>{String(row.ny_date ?? "")}</td>
                  <td>{String(row.source_type ?? "")}</td>
                  <td>{String(row.risk_multiplier ?? "")}</td>
                  <td>{String(row.max_positions ?? "")}</td>
                  <td>{String(row.throttle_reason ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-card">
          <h3>Regime Timeline</h3>
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Regime</th>
                <th>Reasons</th>
              </tr>
            </thead>
            <tbody>
              {regimes.map((row, idx) => (
                <tr key={`${row.ny_date}-${row.regime_id}-${idx}`}>
                  <td>{String(row.ny_date ?? "")}</td>
                  <td>{String(row.regime_id ?? "")}</td>
                  <td className="mono">{String(row.reason_codes_json ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

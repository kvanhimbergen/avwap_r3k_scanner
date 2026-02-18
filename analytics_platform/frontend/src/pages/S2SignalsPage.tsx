import { useMemo, useState } from "react";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

export function S2SignalsPage() {
  const [symbol, setSymbol] = useState("");
  const [reason, setReason] = useState("");

  const signals = usePolling(
    () => api.s2Signals({ symbol: symbol || undefined, reason_code: reason || undefined, limit: 1000 }),
    45_000
  );

  if (signals.loading) return <LoadingState text="Loading S2 signals..." />;
  if (signals.error) return <ErrorState error={signals.error} />;

  const rows = (signals.data?.data.rows ?? []) as Array<Record<string, unknown>>;

  return (
    <section>
      <h2 className="page-title">S2 Signal Audit</h2>
      <p className="page-subtitle">S2 eligibility, selection, and reason code analysis</p>
      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          This is your S2 explainability view. <strong>Eligible=true</strong> means the symbol passed hard gates and
          confluence. <strong>Selected=true</strong> means it survived ranking/cap logic for that run. Use{" "}
          <strong>reason_codes_json</strong> to identify the most common disqualifiers during paper tuning.
        </p>
      </div>
      <div className="filter-row">
        <input
          placeholder="Filter symbol"
          value={symbol}
          onChange={(event) => setSymbol(event.target.value.toUpperCase())}
        />
        <input
          placeholder="Reason contains"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Symbol</th>
              <th>Eligible</th>
              <th>Selected</th>
              <th>Score</th>
              <th>Reasons</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={`${row.run_id}-${row.symbol}-${idx}`}>
                <td>{String(row.asof_date ?? "")}</td>
                <td>{String(row.symbol ?? "")}</td>
                <td>{String(row.eligible ?? false)}</td>
                <td>{String(row.selected ?? false)}</td>
                <td>{row.score === null ? "" : String(row.score ?? "")}</td>
                <td className="mono">{String(row.reason_codes_json ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

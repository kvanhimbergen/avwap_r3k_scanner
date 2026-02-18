import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

const getType = (id: string) => {
  if (id.startsWith("S1")) return "s1";
  if (id.startsWith("S2")) return "s2";
  return "raec";
};

const typeLabel = (t: string) => t.toUpperCase();

const formatCurrency = (val: number | null | undefined) =>
  val != null ? `$${val.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—";

export function StrategyMatrixPage() {
  const matrix = usePolling(() => api.strategyMatrix(), 60_000);

  if (matrix.loading) return <LoadingState text="Loading strategy matrix..." />;
  if (matrix.error) return <ErrorState error={matrix.error} />;

  const data = matrix.data?.data as Record<string, any> ?? {};
  const strategies: any[] = data.strategies ?? [];
  const symbolOverlap: any[] = data.symbol_overlap ?? [];

  return (
    <section>
      <h2 className="page-title">Strategy Matrix</h2>

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          This page compares all strategies side-by-side. Use it to identify{" "}
          <strong>symbol overlap</strong>, compare <strong>activity levels</strong>,
          and understand how each strategy contributes to overall portfolio exposure.
        </p>
      </div>

      {/* Strategy cards grid */}
      {strategies.length > 0 && (
        <div className="matrix-grid">
          {strategies.map((s: any) => {
            const t = getType(s.strategy_id);
            const trades = s.trade_count ?? s.rebalance_count ?? 0;
            return (
              <div key={s.strategy_id} className={`matrix-card type-${t}`}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>{s.strategy_id}</div>
                <span className={`type-badge type-${t}`}>{typeLabel(t)}</span>
                <div className="matrix-stat">Trades: <strong>{trades}</strong></div>
                <div className="matrix-stat">Symbols: <strong>{s.unique_symbols ?? 0}</strong></div>
                {s.latest_regime && (
                  <div className="matrix-stat">
                    Regime:{" "}
                    <span className={`regime-badge ${s.latest_regime.toLowerCase().replace("_", "-")}`}>
                      {s.latest_regime}
                    </span>
                  </div>
                )}
                <div className="matrix-stat">Exposure: <strong>{formatCurrency(s.exposure)}</strong></div>
              </div>
            );
          })}
        </div>
      )}

      {/* Comparison table */}
      {strategies.length > 0 && (
        <div className="table-card">
          <h3>Strategy Comparison</h3>
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Type</th>
                <th>Trades</th>
                <th>Symbols</th>
                <th>Regime</th>
                <th>Exposure</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s: any) => {
                const t = getType(s.strategy_id);
                const trades = s.trade_count ?? s.rebalance_count ?? 0;
                return (
                  <tr key={s.strategy_id}>
                    <td style={{ fontWeight: 600 }}>{s.strategy_id}</td>
                    <td><span className={`type-badge type-${t}`}>{typeLabel(t)}</span></td>
                    <td className="mono">{trades}</td>
                    <td className="mono">{s.unique_symbols ?? 0}</td>
                    <td>
                      {s.latest_regime ? (
                        <span className={`regime-badge ${s.latest_regime.toLowerCase().replace("_", "-")}`}>
                          {s.latest_regime}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="mono">{formatCurrency(s.exposure)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Symbol overlap */}
      {symbolOverlap.length > 0 && (
        <div className="table-card">
          <h3>Symbol Overlap</h3>
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Strategies</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {symbolOverlap.map((row: any) => {
                const ids: string[] = row.strategy_ids ?? [];
                const highlight = ids.length >= 3;
                return (
                  <tr key={row.symbol} style={highlight ? { backgroundColor: "rgba(221, 107, 32, 0.1)" } : undefined}>
                    <td><strong>{row.symbol}</strong></td>
                    <td>{ids.join(", ")}</td>
                    <td className="mono" style={highlight ? { color: "#dd6b20", fontWeight: 700 } : undefined}>
                      {ids.length}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

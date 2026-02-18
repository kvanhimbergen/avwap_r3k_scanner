/**
 * AllocationBar — dual horizontal bar showing target vs current allocation per symbol.
 * Used in Strategy Tearsheet to visualize allocation drift.
 */
export interface AllocationRow {
  symbol: string;
  targetPct: number;
  currentPct: number;
}

export function AllocationBar({ rows }: { rows: AllocationRow[] }) {
  if (rows.length === 0) {
    return <div className="text-tertiary" style={{ fontSize: "0.78rem" }}>No allocation data</div>;
  }

  const maxPct = Math.max(...rows.map((r) => Math.max(r.targetPct, r.currentPct)), 1);

  return (
    <div>
      {rows.map((row) => (
        <div key={row.symbol} style={{ marginBottom: 10 }}>
          <div className="alloc-bar-row">
            <span className="alloc-bar-label">{row.symbol}</span>
            <div className="alloc-bar-track">
              <div
                className="alloc-bar-fill target"
                style={{ width: `${(row.targetPct / maxPct) * 100}%` }}
              />
            </div>
            <span className="alloc-bar-pct">{row.targetPct.toFixed(1)}%</span>
          </div>
          <div className="alloc-bar-row" style={{ marginTop: 2 }}>
            <span className="alloc-bar-label" style={{ color: "var(--text-tertiary)" }} />
            <div className="alloc-bar-track">
              <div
                className="alloc-bar-fill current"
                style={{ width: `${(row.currentPct / maxPct) * 100}%` }}
              />
            </div>
            <span className="alloc-bar-pct" style={{ color: "var(--text-tertiary)" }}>
              {row.currentPct.toFixed(1)}%
            </span>
          </div>
        </div>
      ))}
      <div style={{ display: "flex", gap: 16, fontSize: "0.65rem", color: "var(--text-tertiary)", marginTop: 4 }}>
        <span><span style={{ display: "inline-block", width: 10, height: 4, background: "var(--blue)", borderRadius: 2, marginRight: 4 }} />Target</span>
        <span><span style={{ display: "inline-block", width: 10, height: 4, background: "var(--blue)", opacity: 0.4, borderRadius: 2, marginRight: 4 }} />Current</span>
      </div>
    </div>
  );
}

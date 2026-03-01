/**
 * SignalsPanel — displays key signals for a strategy.
 * Shows SMA values, vol target/realized, momentum scores, anchor info.
 */
export interface SignalRow {
  label: string;
  value: string | number;
  highlight?: boolean;
}

export interface MomentumScore {
  symbol: string;
  score: number;
  returnPct: number;
  period: string;
}

export function SignalsPanel({
  signals,
  momentum,
  volTarget,
  volRealized,
}: {
  signals: SignalRow[];
  momentum?: MomentumScore[];
  volTarget?: number | null;
  volRealized?: number | null;
}) {
  return (
    <div>
      {signals.length > 0 && (
        <div style={{ marginBottom: momentum?.length ? 12 : 0 }}>
          {signals.map((s) => (
            <div key={s.label} className="signal-row">
              <span className="signal-label">{s.label}</span>
              <span className="signal-dots" />
              <span className={`signal-value${s.highlight ? " text-green" : ""}`}>{s.value}</span>
            </div>
          ))}
        </div>
      )}

      {momentum && momentum.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div className="signal-section-label">Momentum Scores</div>
          {momentum.map((m) => (
            <div key={m.symbol} className="signal-row">
              <span className="signal-label font-mono">{m.symbol}</span>
              <span className="signal-value font-mono">{m.score.toFixed(2)}</span>
              <span className={`signal-value font-mono ${m.returnPct >= 0 ? "text-green" : "text-red"}`}>
                {m.returnPct >= 0 ? "+" : ""}{m.returnPct.toFixed(1)}% ({m.period})
              </span>
            </div>
          ))}
        </div>
      )}

      {(volTarget != null || volRealized != null) && (
        <div style={{ marginTop: 8 }}>
          {volTarget != null && (
            <div className="signal-row">
              <span className="signal-label">Vol Target</span>
              <span className="signal-dots" />
              <span className="signal-value">{volTarget.toFixed(1)}%</span>
            </div>
          )}
          {volRealized != null && (
            <div className="signal-row">
              <span className="signal-label">Vol Realized</span>
              <span className="signal-dots" />
              <span className="signal-value">{volRealized.toFixed(1)}%</span>
            </div>
          )}
        </div>
      )}

      {signals.length === 0 && !momentum?.length && volTarget == null && volRealized == null && (
        <div className="text-tertiary" style={{ fontSize: "0.78rem" }}>No signal data available</div>
      )}
    </div>
  );
}

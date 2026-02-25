/**
 * Book-level P&L strip — two side-by-side panels for Alpaca and Schwab books.
 * First thing a PM looks at: "How much money do I have and how is it doing today?"
 */
import type { PortfolioPosition } from "../types";

export interface BookData {
  title: string;
  subtitle: string;
  metrics: { label: string; value: string }[];
  positions?: PortfolioPosition[];
}

export function BookPnlPanel({
  alpaca,
  schwab,
}: {
  alpaca: BookData | null;
  schwab: BookData | null;
}) {
  return (
    <div className="book-pnl-grid">
      {alpaca && <BookCard data={alpaca} accentClass="alpaca" />}
      {schwab && <BookCard data={schwab} accentClass="schwab" />}
    </div>
  );
}

function fmtUsd(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function BookCard({
  data,
  accentClass,
}: {
  data: BookData;
  accentClass: string;
}) {
  const positions = data.positions ?? [];

  return (
    <div className="book-pnl-card">
      <div className="book-pnl-header">
        <span className="book-pnl-title">{data.title}</span>
        <span className={`book-badge ${accentClass}`}>{data.subtitle}</span>
      </div>
      <div className="book-pnl-metrics">
        {data.metrics.map((m, i) => (
          <div key={m.label}>
            <div className="book-pnl-metric-label">{m.label}</div>
            <div className={`book-pnl-metric-value${i === 0 ? " headline" : ""}`}>{m.value}</div>
          </div>
        ))}
      </div>
      {positions.length > 0 && (
        <div className="book-pnl-positions">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Qty</th>
                <th>Price</th>
                <th>Notional</th>
                <th>Wt %</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={`${p.strategy_id}-${p.symbol}`}>
                  <td className="font-mono font-bold">{p.symbol}</td>
                  <td className="font-mono">{p.qty}</td>
                  <td className="font-mono">{p.mark_price != null ? `$${p.mark_price.toFixed(2)}` : "\u2014"}</td>
                  <td className="font-mono">{fmtUsd(p.notional)}</td>
                  <td className="font-mono">{p.weight_pct.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

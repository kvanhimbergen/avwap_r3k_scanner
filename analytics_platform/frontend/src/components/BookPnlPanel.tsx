/**
 * Book-level P&L strip — two side-by-side panels for Alpaca and Schwab books.
 * First thing a PM looks at: "How much money do I have and how is it doing today?"
 */

export interface BookData {
  title: string;
  subtitle: string;
  metrics: { label: string; value: string }[];
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

function BookCard({
  data,
  accentClass,
}: {
  data: BookData;
  accentClass: string;
}) {
  return (
    <div className="book-pnl-card">
      <div className="book-pnl-header">
        <span className="book-pnl-title">{data.title}</span>
        <span className={`book-badge ${accentClass}`}>{data.subtitle}</span>
      </div>
      <div className="book-pnl-metrics">
        {data.metrics.map((m) => (
          <div key={m.label}>
            <div className="book-pnl-metric-label">{m.label}</div>
            <div className="book-pnl-metric-value">{m.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

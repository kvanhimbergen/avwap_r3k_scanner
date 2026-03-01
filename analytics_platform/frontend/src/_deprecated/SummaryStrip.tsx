/**
 * Compact horizontal KPI row — used for inline metric summaries.
 */
export function SummaryStrip({
  items,
}: {
  items: { label: string; value: string | number }[];
}) {
  return (
    <div className="summary-strip">
      {items.map((item, i) => (
        <span key={item.label}>
          {i > 0 && <span className="summary-strip-divider" style={{ display: "inline-block", marginRight: 16 }} />}
          <span className="summary-strip-item">
            <span className="summary-strip-label">{item.label}:</span>
            <span className="summary-strip-value">{item.value}</span>
          </span>
        </span>
      ))}
    </div>
  );
}

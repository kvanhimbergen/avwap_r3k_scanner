export function KpiCard({ label, value, subtext }: { label: string; value: string | number; subtext?: string }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {subtext ? <div className="kpi-subtext">{subtext}</div> : null}
    </div>
  );
}

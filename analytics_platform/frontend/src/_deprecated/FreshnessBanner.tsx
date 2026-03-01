import type { FreshnessRow } from "../types";

export function FreshnessBanner({ rows }: { rows: FreshnessRow[] }) {
  const stale = rows.filter((row) => row.parse_status !== "ok" || row.file_count === 0);
  if (!stale.length) {
    return <div className="banner banner-ok">All monitored sources are healthy.</div>;
  }
  return (
    <div className="banner banner-warn">
      {stale.length} source(s) need attention: {stale.map((s) => s.source_name).join(", ")}
    </div>
  );
}

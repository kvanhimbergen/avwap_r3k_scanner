/**
 * Pulsing skeleton placeholder for loading states.
 */
export function SkeletonLoader({
  variant = "card",
  count = 1,
}: {
  variant?: "text" | "card" | "chart";
  count?: number;
}) {
  const cls = `skeleton skeleton-${variant}`;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className={cls} />
      ))}
    </div>
  );
}

/** Skeleton grid matching the strategy card layout. */
export function SkeletonGrid({ count = 8 }: { count?: number }) {
  return (
    <div className="strategy-grid">
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="skeleton"
          style={{ height: 100, borderRadius: "var(--radius-md)" }}
        />
      ))}
    </div>
  );
}

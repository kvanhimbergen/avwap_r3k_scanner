export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-vantage-border/50 ${className}`} />;
}

export function SkeletonCard() {
  return (
    <div className="bg-vantage-card border border-vantage-border rounded-lg p-4 space-y-3">
      <Skeleton className="h-3 w-20" />
      <Skeleton className="h-7 w-32" />
      <Skeleton className="h-3 w-full" />
    </div>
  );
}

export function SkeletonTable() {
  return (
    <div className="bg-vantage-card border border-vantage-border rounded-lg p-4 space-y-2">
      <Skeleton className="h-3 w-40 mb-3" />
      {[...Array(5)].map((_, i) => (
        <Skeleton key={i} className="h-6 w-full" />
      ))}
    </div>
  );
}

export function SkeletonChart() {
  return (
    <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
      <Skeleton className="h-3 w-32 mb-3" />
      <Skeleton className="h-[280px] w-full" />
    </div>
  );
}

/**
 * Displays a "Last refreshed" timestamp for data panels.
 * Shows relative time (e.g., "< 1m ago", "3m ago").
 */
import { useEffect, useState } from "react";

function formatAge(date: Date): string {
  const sec = Math.floor((Date.now() - date.getTime()) / 1000);
  if (sec < 60) return "< 1m ago";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  return `${hr}h ago`;
}

export function LastRefreshed({ at }: { at: Date | null }) {
  const [, tick] = useState(0);

  // Re-render every 30s to keep the relative time fresh
  useEffect(() => {
    if (!at) return;
    const id = window.setInterval(() => tick((n) => n + 1), 30_000);
    return () => window.clearInterval(id);
  }, [at]);

  if (!at) return null;

  return (
    <span className="last-refreshed" title={at.toLocaleTimeString()}>
      Updated {formatAge(at)}
    </span>
  );
}

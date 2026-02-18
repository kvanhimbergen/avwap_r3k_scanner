import { useEffect, useRef, useState } from "react";

export interface PollState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  lastRefreshed: Date | null;
  refresh: () => Promise<void>;
}

export function usePolling<T>(loader: () => Promise<T>, intervalMs = 45_000): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const mounted = useRef(true);

  const refresh = async () => {
    try {
      const next = await loader();
      if (!mounted.current) {
        return;
      }
      setData(next);
      setError(null);
      setLastRefreshed(new Date());
    } catch (err) {
      if (!mounted.current) {
        return;
      }
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      if (mounted.current) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, intervalMs);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, [intervalMs]);

  return { data, loading, error, lastRefreshed, refresh };
}

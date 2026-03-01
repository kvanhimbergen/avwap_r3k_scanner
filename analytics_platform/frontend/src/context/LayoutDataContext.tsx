import { createContext, useContext, type ReactNode } from "react";
import { api } from "../api";
import { usePolling, type PollState } from "../hooks/usePolling";

interface LayoutData {
  portfolio: PollState<any>;
  health: PollState<any>;
  raec: PollState<any>;
}

const LayoutDataContext = createContext<LayoutData | null>(null);

export function LayoutDataProvider({ children }: { children: ReactNode }) {
  const portfolio = usePolling(() => api.portfolioOverview(), 60_000);
  const health = usePolling(() => api.health(), 60_000);
  const raec = usePolling(() => api.raecDashboard(), 60_000);

  return (
    <LayoutDataContext.Provider value={{ portfolio, health, raec }}>
      {children}
    </LayoutDataContext.Provider>
  );
}

export function useLayoutData(): LayoutData {
  const ctx = useContext(LayoutDataContext);
  if (!ctx) throw new Error("useLayoutData must be used within LayoutDataProvider");
  return ctx;
}

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the api module
vi.mock("../api", () => ({
  api: {
    raecDashboard: vi.fn().mockResolvedValue({
      data: { summary: { total_rebalance_events: 0, by_strategy: [] }, regime_history: [], allocation_snapshots: [] },
    }),
    journal: vi.fn().mockResolvedValue({ data: { count: 0, rows: [] } }),
    raecReadiness: vi.fn().mockResolvedValue({ data: { strategies: [], coordinator: {} } }),
    pnl: vi.fn().mockResolvedValue({ data: { by_strategy: [] } }),
  },
}));

import { RaecDashboardPage } from "../pages/RaecDashboardPage";
import { JournalPage } from "../pages/JournalPage";
import { ReadinessPage } from "../pages/ReadinessPage";
import { PnlPage } from "../pages/PnlPage";

describe("RAEC pages render without crashing", () => {
  it("RaecDashboardPage", async () => {
    render(<MemoryRouter><RaecDashboardPage /></MemoryRouter>);
    // Should show loading initially
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("JournalPage", async () => {
    render(<MemoryRouter><JournalPage /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("ReadinessPage", async () => {
    render(<MemoryRouter><ReadinessPage /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("PnlPage", async () => {
    render(<MemoryRouter><PnlPage /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});

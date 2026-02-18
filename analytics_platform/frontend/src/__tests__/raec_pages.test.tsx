import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the api module
vi.mock("../api", () => ({
  api: {
    riskControls: vi.fn().mockResolvedValue({
      data: { risk_controls: [], regimes: [] },
    }),
    decisionsTimeseries: vi.fn().mockResolvedValue({
      data: { points: [] },
    }),
    pnl: vi.fn().mockResolvedValue({ data: { by_strategy: [], allocation_drift: [] } }),
    portfolioOverview: vi.fn().mockResolvedValue({ data: {} }),
    freshness: vi.fn().mockResolvedValue({ data: { rows: [] } }),
    health: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

import { RiskPage } from "../pages/RiskPage";
import { SystemPage } from "../pages/SystemPage";

describe("Phase 4 consolidated pages render without crashing", () => {
  it("RiskPage (expanded risk monitor)", async () => {
    render(<MemoryRouter><RiskPage /></MemoryRouter>);
    expect(screen.getByText(/risk monitor/i)).toBeInTheDocument();
  });

  it("SystemPage (ops/system)", async () => {
    render(<MemoryRouter><SystemPage /></MemoryRouter>);
    expect(screen.getByText("System & Operations")).toBeInTheDocument();
  });
});

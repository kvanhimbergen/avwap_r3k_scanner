import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../api", () => ({
  api: {
    slippage: vi.fn().mockResolvedValue({
      data: { summary: {}, by_bucket: [], by_time: [], by_symbol: [], trend: [] },
    }),
    tradeAnalytics: vi.fn().mockResolvedValue({
      data: { per_strategy: [], daily_frequency: [], symbol_concentration: [] },
    }),
    journal: vi.fn().mockResolvedValue({ data: { count: 0, rows: [] } }),
  },
}));

import { ExecutionPage } from "../pages/ExecutionPage";
import { BlotterPage } from "../pages/BlotterPage";

describe("Phase 4 pages render without crashing", () => {
  it("ExecutionPage", async () => {
    render(<MemoryRouter><ExecutionPage /></MemoryRouter>);
    expect(screen.getByText("Execution")).toBeInTheDocument();
  });

  it("BlotterPage", async () => {
    render(<MemoryRouter><BlotterPage /></MemoryRouter>);
    expect(screen.getByText("Blotter")).toBeInTheDocument();
  });
});

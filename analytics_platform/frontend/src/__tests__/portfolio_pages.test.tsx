import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../api", () => ({
  api: {
    portfolioOverview: vi.fn().mockResolvedValue({
      data: { latest: {}, positions: [], exposure_by_strategy: [], history: [] },
    }),
    strategyMatrix: vi.fn().mockResolvedValue({
      data: { strategies: [], symbol_overlap: [] },
    }),
    slippage: vi.fn().mockResolvedValue({
      data: { summary: {}, by_bucket: [], by_time: [], by_symbol: [], trend: [] },
    }),
    tradeAnalytics: vi.fn().mockResolvedValue({
      data: { per_strategy: [], daily_frequency: [], symbol_concentration: [] },
    }),
  },
}));

import { PortfolioPage } from "../pages/PortfolioPage";
import { StrategyMatrixPage } from "../pages/StrategyMatrixPage";
import { SlippagePage } from "../pages/SlippagePage";
import { TradeAnalyticsPage } from "../pages/TradeAnalyticsPage";

describe("Portfolio & analytics pages render without crashing", () => {
  it("PortfolioPage", async () => {
    render(<MemoryRouter><PortfolioPage /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("StrategyMatrixPage", async () => {
    render(<MemoryRouter><StrategyMatrixPage /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("SlippagePage", async () => {
    render(<MemoryRouter><SlippagePage /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("TradeAnalyticsPage", async () => {
    render(<MemoryRouter><TradeAnalyticsPage /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../api", () => ({
  api: {
    performance: vi.fn().mockResolvedValue({
      data: {
        swing_metrics: {},
        portfolio_metrics: {
          total_return: null,
          annualized_return: null,
          sharpe_ratio: null,
          sortino_ratio: null,
          max_drawdown: null,
          calmar_ratio: null,
          data_points: 0,
          equity_curve: [],
          benchmark: "SPY",
          benchmark_return: null,
          excess_return: null,
          benchmark_curve: [],
          data_sufficient: false,
        },
        raec_metrics: {},
        order_log: [],
      },
    }),
  },
}));

import { PerformancePage } from "../pages/PerformancePage";

describe("PerformancePage", () => {
  it("renders heading", async () => {
    render(
      <MemoryRouter>
        <PerformancePage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Performance" })).toBeInTheDocument();
  });

  it("shows insufficient data message", async () => {
    render(
      <MemoryRouter>
        <PerformancePage />
      </MemoryRouter>,
    );
    const msg = await screen.findByText(/Need 10\+ portfolio snapshots/);
    expect(msg).toBeInTheDocument();
  });
});

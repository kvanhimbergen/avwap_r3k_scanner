import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../api", () => ({
  api: {
    getFills: vi.fn().mockResolvedValue({
      data: { records: [] },
    }),
    postFills: vi.fn().mockResolvedValue({
      data: { logged: 0, skipped: 0, records: [] },
    }),
  },
}));

import { LogFillsPage } from "../pages/LogFillsPage";

describe("LogFillsPage", () => {
  it("renders without crashing", () => {
    render(
      <MemoryRouter>
        <LogFillsPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Log Fills" })).toBeInTheDocument();
  });

  it("shows the form elements", () => {
    render(
      <MemoryRouter>
        <LogFillsPage />
      </MemoryRouter>,
    );
    expect(screen.getByText("+ Add Row")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log Fills" })).toBeInTheDocument();
  });
});

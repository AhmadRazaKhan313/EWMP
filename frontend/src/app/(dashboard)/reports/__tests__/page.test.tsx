import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ReportsPage from "../page";

const download = vi.fn();
const state = {
  catalog: {
    data: {
      can_export: true,
      items: [
        { key: "payroll-expenses", title: "Monthly Payroll Expenses", category: "Payroll", description: "d1", uses_search: false },
        { key: "payroll-register", title: "Payroll Register", category: "Payroll", description: "d2", uses_search: true },
        { key: "attendance-monthly", title: "Monthly Attendance Summary", category: "Attendance", description: "d3", uses_search: true },
      ],
    },
    isLoading: false, isError: false,
  },
};

vi.mock("@/services/reports.service", () => ({
  currentMonth: () => "2026-10",
  useReportCatalog: () => state.catalog,
  useDepartmentOptions: () => ({ data: [{ id: "d1", name: "Engineering" }] }),
  useHubReport: (key: string | null) => ({
    isLoading: false, isError: false, refetch: vi.fn(),
    data: key ? {
      key, title: "T", subtitle: "Last 12 months up to October 2026",
      columns: [{ key: "month", label: "Month", type: "text" }, { key: "total_paid_out", label: "Total paid out", type: "money" }],
      rows: [{ month: "October 2026", total_paid_out: 113000 }],
      totals: { month: "Total", total_paid_out: 155000 },
      summary: [{ label: "Total paid out", value: 113000, type: "money" }],
      notes: ["Only approved, locked or paid payroll runs are counted."],
    } : undefined,
  }),
  downloadHubReport: (...a: unknown[]) => download(...a),
}));

beforeEach(() => { download.mockReset(); download.mockResolvedValue(undefined); });

describe("ReportsPage", () => {
  it("groups reports by category and opens the first one", () => {
    render(<ReportsPage />);
    expect(screen.getByText("Payroll")).toBeInTheDocument();
    expect(screen.getByText("Attendance")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Monthly Payroll Expenses" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("113,000.00", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("155,000.00")).toBeInTheDocument();
    expect(screen.getByText(/Only approved, locked or paid/)).toBeInTheDocument();
  });

  it("shows the search box only for reports that use it", () => {
    render(<ReportsPage />);
    expect(screen.queryByLabelText("Search employees")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Payroll Register" }));
    expect(screen.getByLabelText("Search employees")).toBeInTheDocument();
  });

  it("downloads Excel for the open report and month", async () => {
    render(<ReportsPage />);
    fireEvent.click(screen.getByRole("button", { name: /Download Excel/ }));
    await waitFor(() => expect(download).toHaveBeenCalled());
    const args = download.mock.calls[0] ?? [];
    expect(args[0]).toBe("payroll-expenses");
    expect(args[1]).toBe("xlsx");
    expect(args[2]).toMatchObject({ month: "2026-10" });
  });

  it("hides the download buttons without export permission", () => {
    state.catalog = { ...state.catalog, data: { ...state.catalog.data, can_export: false } };
    render(<ReportsPage />);
    expect(screen.queryByRole("button", { name: /Download Excel/ })).toBeNull();
    state.catalog = { ...state.catalog, data: { ...state.catalog.data, can_export: true } };
  });

  it("shows an empty state when nothing is allowed", () => {
    const saved = state.catalog;
    state.catalog = { data: { can_export: false, items: [] }, isLoading: false, isError: false };
    render(<ReportsPage />);
    expect(screen.getByText("No reports available")).toBeInTheDocument();
    state.catalog = saved;
  });
});

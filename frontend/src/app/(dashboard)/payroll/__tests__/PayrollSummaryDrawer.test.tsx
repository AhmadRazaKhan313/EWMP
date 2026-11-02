/** B-04: the payroll summary drawer shows totals, components and departments. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PayrollSummaryDrawer } from "../PayrollSummaryDrawer";

const SUMMARY = {
  run: { id: "r1", name: "September", status: "review", currency: "PKR", period_start: "2026-09-01", period_end: "2026-09-30", pay_date: "2026-09-30" },
  totals: { employee_count: 2, gross: "200000.00", deductions: "20000.00", net: "180000.00", average_net: "90000.00" },
  attendance: { absent_days: "1.00", leave_days: "0.00", unpaid_leave_days: "0.00", overtime_hours: "3.00" },
  by_component: [
    { type: "earning", code: "BASIC", name: "Basic Salary", total: "200000.00", employee_count: 2 },
    { type: "deduction", code: "TAX", name: "Income Tax", total: "20000.00", employee_count: 2 },
  ],
  by_department: [{ department_id: null, department_name: "No department", employee_count: 2, gross: "200000.00", deductions: "20000.00", net: "180000.00" }],
  matches_run_totals: true,
};

vi.mock("@/services/api-client", () => ({ default: { get: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import apiClient from "@/services/api-client";

function renderDrawer() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><PayrollSummaryDrawer runId="r1" onClose={() => {}} /></QueryClientProvider>);
}

describe("PayrollSummaryDrawer", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows totals, components grouped by type, and departments", async () => {
    (apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: SUMMARY });
    renderDrawer();
    expect(await screen.findByText("Basic Salary")).toBeTruthy();
    expect(screen.getByText("Earnings")).toBeTruthy();
    expect(screen.getAllByText("Deductions").length).toBeGreaterThanOrEqual(2); // summary card + component group
    expect(screen.getByText("No department")).toBeTruthy();
    expect(screen.queryByText(/run header totals differ/i)).toBeNull();
    expect(apiClient.get).toHaveBeenCalledWith("/payroll/runs/r1/summary");
  });

  it("warns when the run header no longer matches its payslips", async () => {
    (apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { ...SUMMARY, matches_run_totals: false } });
    renderDrawer();
    expect(await screen.findByText(/run header totals differ/i)).toBeTruthy();
  });
});

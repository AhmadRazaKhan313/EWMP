/** Every dashboard quick action points at a page that exists. */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import fs from "node:fs";
import path from "node:path";

// recharts needs ResizeObserver, which jsdom does not provide.
vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });

vi.mock("@/services/api-client", () => ({ default: { get: vi.fn().mockResolvedValue({ data: null }) } }));
vi.mock("@/store/auth.store", () => {
  const state = {
    user: { first_name: "Admin", is_platform_admin: true },
    hasPermission: () => true,
    hasRole: () => true,
  };
  const useAuthStore = (sel?: (s: typeof state) => unknown) => (sel ? sel(state) : state);
  return { useAuthStore };
});

import DashboardPage from "../page";

const APP = path.resolve(__dirname, "../..");

function routeExists(href: string): boolean {
  const clean = href.split("?")[0]!.replace(/^\//, "");
  return fs.existsSync(path.join(APP, clean, "page.tsx"));
}

describe("dashboard quick actions", () => {
  it("links every action to an existing page, with the create flows on their own routes", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><DashboardPage /></QueryClientProvider>);
    const link = (name: string) => screen.getByText(name).closest("a")!.getAttribute("href")!;
    expect(link("Add Employee")).toBe("/employees/new");
    expect(link("Process Payroll")).toBe("/payroll/new");
    expect(link("Assign Asset")).toBe("/assets/assign");
    expect(link("Apply for Leave")).toBe("/leave/new");
    expect(link("My Payslips")).toBe("/payroll/my");
    expect(link("Raise a Ticket")).toBe("/helpdesk/new");
    for (const name of ["Add Employee", "Process Payroll", "Team Attendance", "Assign Asset", "My Attendance",
      "Apply for Leave", "My Payslips", "Raise a Ticket"]) {
      expect(routeExists(link(name)), `${name} -> ${link(name)}`).toBe(true);
    }
  });

  it("shows the Absent Today card for a user with attendance access", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><DashboardPage /></QueryClientProvider>);
    expect(screen.getByRole("button", { name: /absent today/i })).toBeTruthy();
  });
});

describe("work hours widget", () => {
  it("draws the weekly total against the target from /dashboard/weekly-hours", async () => {
    const api = (await import("@/services/api-client")).default as unknown as { get: ReturnType<typeof vi.fn> };
    api.get.mockImplementation(async (url: string) => ({
      data: url === "/dashboard/weekly-hours"
        ? { week_start: "2026-10-26", week_end: "2026-11-01", total_hours: 32, target_hours: 40, working_days: 5,
            days: ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"].map((d, i) => (
              { date: d, weekday: "x", hours: i < 4 ? 8 : 0, people: 1, is_working_day: i < 5, extra_day: false })) }
        : null,
    }));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><DashboardPage /></QueryClientProvider>);
    expect(await screen.findByText("32h / 40h")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("/dashboard/weekly-hours", { params: { scope: "team" } });
  });
});

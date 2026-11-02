/**
 * The Attendance page offers Edit / Mark per row only to people who may use
 * them: attendance.edit for a recorded day, attendance.regularize for a day
 * with no record; and the dialog opens for the clicked employee.
 *
 * Run:  cd frontend && npm test -- AttendanceAdminActions
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let perms: string[] = [];
vi.mock("@/store/auth.store", () => {
  const useAuthStore = (sel?: (s: unknown) => unknown) => {
    const state = { user: { has_employee_profile: false }, hasPermission: (p: string) => perms.includes(p) };
    return sel ? sel(state) : state;
  };
  return { useAuthStore };
});
vi.mock("../CheckInWidget", () => ({ CheckInWidget: () => null }));
vi.mock("@/services/api-client", () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import apiClient from "@/services/api-client";
import AttendancePage from "../page";

const row = (over: Record<string, unknown>) => ({
  employee_id: "e", employee_code: "C", employee_name: "N", department_name: null, shift_name: null,
  shift_start: null, shift_end: null, status: "present", check_in: null, check_out: null, total_minutes: null,
  late_minutes: null, overtime_minutes: null, is_regularized: false, record_id: null, detail: null, ...over,
});

beforeEach(() => {
  (apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: {
      date: "2026-09-01", total: 2, total_pages: 1,
      summary: { present_total: 1, late: 0, absent: 1, on_leave: 0, not_checked_in: 0, scheduled: 0, holiday: 0, weekly_off: 0 },
      items: [
        row({ employee_id: "e1", employee_code: "E1", employee_name: "Has Record", record_id: "r1", is_regularized: true }),
        row({ employee_id: "e2", employee_code: "E2", employee_name: "No Record", status: "absent" }),
      ],
    },
  });
});

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><AttendancePage /></QueryClientProvider>);
}

describe("attendance page admin actions", () => {
  it("shows no actions to a plain viewer", async () => {
    perms = ["attendance.view"];
    show();
    await screen.findByText("Has Record");
    expect(screen.queryByRole("button", { name: /attendance for/i })).toBeNull();
  });

  it("attendance.edit can correct a recorded day but not mark a missing one", async () => {
    perms = ["attendance.edit"];
    show();
    expect(await screen.findByRole("button", { name: "Correct attendance for Has Record" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark attendance for No Record" })).toBeNull();
    expect(screen.getByText("Corrected")).toBeInTheDocument();
  });

  it("attendance.regularize can mark a missing day and the dialog opens for that person", async () => {
    perms = ["attendance.regularize"];
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Mark attendance for No Record" }));
    expect(screen.getByRole("dialog", { name: /mark attendance/i })).toHaveTextContent("No Record");
    expect(screen.queryByRole("button", { name: "Correct attendance for Has Record" })).toBeNull();
  });
});

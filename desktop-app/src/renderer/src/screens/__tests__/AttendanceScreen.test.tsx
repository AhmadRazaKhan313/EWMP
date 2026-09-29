import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AttendanceScreen from "../AttendanceScreen";
import * as attendanceService from "../../services/attendanceService";
import type { AttendanceRecordItem } from "../../types/hrms";

vi.mock("../../services/attendanceService");

const LATE_RECORD: AttendanceRecordItem = {
  id: "att-1",
  employee_id: "emp-1",
  employee_name: "Ada Lovelace",
  date: "2026-09-14",
  check_in: "2026-09-14T09:05:00Z",
  check_out: "2026-09-14T17:30:00Z",
  status: "late",
  total_minutes: 505,
  overtime_minutes: 0,
  late_minutes: 5,
  is_regularized: false,
};

const WEEKEND_RECORD: AttendanceRecordItem = {
  id: "att-2",
  employee_id: "emp-1",
  employee_name: "Ada Lovelace",
  date: "2026-09-13",
  check_in: null,
  check_out: null,
  status: "weekend",
  total_minutes: null,
  overtime_minutes: null,
  late_minutes: null,
  is_regularized: false,
};

const RECORDS: AttendanceRecordItem[] = [LATE_RECORD, WEEKEND_RECORD];

function renderWithClient(ui: React.ReactElement): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("AttendanceScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders each attendance record with status, times, and total hours", async () => {
    vi.mocked(attendanceService.getMyAttendance).mockResolvedValue(RECORDS);
    renderWithClient(<AttendanceScreen />);

    await waitFor(() => expect(screen.getByTestId("attendance-history-list")).toBeInTheDocument());
    const rows = screen.getAllByTestId("attendance-row");
    expect(rows).toHaveLength(2);
    // Scoped to individual rows rather than the whole document — the
    // stat band above the table also has a "Late" summary tile, so an
    // unscoped getByText("Late") now matches two elements.
    expect(rows[0]).toHaveTextContent("Late");
    expect(rows[1]).toHaveTextContent("Weekend");
    expect(rows[0]).toHaveTextContent("8h 25m");
  });

  it("shows an em dash for check-in/out and hours on a day with no session", async () => {
    vi.mocked(attendanceService.getMyAttendance).mockResolvedValue([WEEKEND_RECORD]);
    renderWithClient(<AttendanceScreen />);

    await waitFor(() => expect(screen.getByTestId("attendance-row")).toBeInTheDocument());
    // Check-in and check-out are separate table cells now, so the old
    // combined "— → —" string is gone; each cell shows its own em dash.
    const row = screen.getByTestId("attendance-row");
    expect(row).toHaveTextContent("Weekend");
    expect(row.textContent).toContain("—");
  });

  it("shows an empty state when there are no records yet", async () => {
    vi.mocked(attendanceService.getMyAttendance).mockResolvedValue([]);
    renderWithClient(<AttendanceScreen />);

    // The empty state names the month being viewed, since the screen can
    // now be paged back through previous months.
    expect(await screen.findByText(/Nothing recorded in/)).toBeInTheDocument();
  });

  it("shows an error message if the request fails (e.g. missing attendance.view_own)", async () => {
    vi.mocked(attendanceService.getMyAttendance).mockRejectedValue(new Error("403"));
    renderWithClient(<AttendanceScreen />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load your attendance history");
  });
});

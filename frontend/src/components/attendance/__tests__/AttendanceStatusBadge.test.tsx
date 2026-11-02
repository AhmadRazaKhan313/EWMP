/**
 * T-04: Absent is the same red pill everywhere, built from the destructive
 * design token (never a hard-coded colour); other statuses keep the Badge.
 *
 * Run:  cd frontend && npm test -- AttendanceStatusBadge
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AttendanceStatusBadge } from "../AttendanceStatusBadge";
import { RecentAttendanceCard } from "../RecentAttendanceCard";

vi.mock("@/services/api-client", () => ({
  default: {
    get: vi.fn().mockResolvedValue({
      data: { items: [
        { id: "1", date: "2026-09-02", status: "absent", check_in: null, check_out: null },
        { id: "2", date: "2026-09-01", status: "present", check_in: "2026-09-01T04:00:00Z", check_out: "2026-09-01T12:00:00Z" },
      ] },
    }),
  },
}));

describe("AttendanceStatusBadge", () => {
  it("renders Absent as a red destructive-token pill", () => {
    render(<AttendanceStatusBadge status="absent" />);
    const badge = screen.getByTestId("absent-badge");
    expect(badge).toHaveTextContent("Absent");
    expect(badge.className).toContain("--destructive");
    expect(badge.className).not.toMatch(/#[0-9a-f]{3,6}|rgb\(|red-\d/i);
  });

  it("renders other statuses as the normal labelled badge", () => {
    render(<><AttendanceStatusBadge status="late" /><AttendanceStatusBadge status="on_leave" /><AttendanceStatusBadge status="half_day" /></>);
    expect(screen.getByText("Late")).toBeInTheDocument();
    expect(screen.getByText("On Leave")).toBeInTheDocument();
    expect(screen.getByText("Half Day")).toBeInTheDocument();
    expect(screen.queryByTestId("absent-badge")).toBeNull();
  });

  it("falls back to a readable label for an unknown status", () => {
    render(<AttendanceStatusBadge status="some_new_status" />);
    expect(screen.getByText("some new status")).toBeInTheDocument();
  });
});

describe("RecentAttendanceCard", () => {
  it("shows the employee's recent days with Absent in red", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><RecentAttendanceCard employeeId="e1" /></QueryClientProvider>);
    expect(await screen.findByTestId("absent-badge")).toBeInTheDocument();
    expect(screen.getByText("2026-09-01")).toBeInTheDocument();
    expect(screen.getByText("Present")).toBeInTheDocument();
  });
});

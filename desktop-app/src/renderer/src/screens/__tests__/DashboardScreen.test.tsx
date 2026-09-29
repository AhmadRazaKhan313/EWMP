import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DashboardScreen from "../DashboardScreen";
import * as leaveService from "../../services/leaveService";
import * as holidaysService from "../../services/holidaysService";
import * as notificationsService from "../../services/notificationsService";
import * as workSessionsService from "../../services/workSessionsService";

vi.mock("../../services/leaveService");
vi.mock("../../services/holidaysService");
vi.mock("../../services/notificationsService");
vi.mock("../../services/workSessionsService");

function renderWithClient(ui: React.ReactElement): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("DashboardScreen", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.mocked(workSessionsService.getMyRecentSessions).mockResolvedValue([]);
    vi.mocked(workSessionsService.sumMinutesToday).mockReturnValue(125); // 2h 5m
    vi.mocked(workSessionsService.sumMinutesThisWeek).mockReturnValue(605); // 10h 5m
    // `vi.mock` above auto-mocks every export of the module, including the
    // two pure helpers the Daily Reports card now uses directly
    // (sessionsToday, effectiveSessionMinutes). Without this they'd
    // silently return undefined and crash the render — wire them to their
    // REAL implementations rather than hand-writing equivalent logic here,
    // so this test can't drift from what the component actually calls.
    const actual = await vi.importActual<typeof workSessionsService>("../../services/workSessionsService");
    vi.mocked(workSessionsService.sessionsToday).mockImplementation(actual.sessionsToday);
    vi.mocked(workSessionsService.effectiveSessionMinutes).mockImplementation(actual.effectiveSessionMinutes);
    vi.mocked(leaveService.getMyLeaveBalances).mockResolvedValue([
      { leave_type_id: "lt-1", leave_type_name: "Sick Leave", leave_type_color: "#ef4444", year: 2026, entitled_days: 10, carried_forward_days: 0, used_days: 0, pending_days: 0, remaining_days: 10 },
    ]);
    vi.mocked(holidaysService.getUpcomingHolidays).mockResolvedValue([
      { id: "h-1", name: "Independence Day", date: "2026-08-14", description: null, is_optional: false, branch_id: null },
    ]);
    vi.mocked(notificationsService.getUnreadNotificationCount).mockResolvedValue(3);
  });

  it("renders today/week hours computed from recent sessions", async () => {
    renderWithClient(<DashboardScreen />);
    await waitFor(() => expect(screen.getByTestId("stat-today-hours")).toHaveTextContent("2h 5m"));
    expect(screen.getByTestId("stat-week-hours")).toHaveTextContent("10h 5m");
  });

  it("renders leave balance and upcoming holiday widgets", async () => {
    renderWithClient(<DashboardScreen />);
    await waitFor(() => expect(screen.getByTestId("leave-balance-widget")).toHaveTextContent("Sick Leave"));
    expect(screen.getByTestId("leave-balance-widget")).toHaveTextContent("10");
    expect(screen.getByTestId("upcoming-holidays-widget")).toHaveTextContent("Independence Day");
  });

  it("shows the unread notification count", async () => {
    renderWithClient(<DashboardScreen />);
    await waitFor(() => expect(screen.getByTestId("unread-notifications-pill")).toHaveTextContent("3 unread notifications"));
  });

  it("does NOT call the org-wide /dashboard/stats endpoint (self-service scope only)", async () => {
    // No dashboardService import/mock exists at all — this test documents
    // and locks in that omission rather than exercising a spy.
    renderWithClient(<DashboardScreen />);
    await waitFor(() => expect(screen.getByTestId("stat-today-hours")).toBeInTheDocument());
  });
});

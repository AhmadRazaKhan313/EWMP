import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LeaveScreen from "../LeaveScreen";
import * as leaveService from "../../services/leaveService";

vi.mock("../../services/leaveService");

const TYPES = [
  { id: "lt-1", name: "Annual Leave", code: "AL", color: "#3b82f6", days_per_year: "20", is_paid: true, requires_approval: true, requires_document: false, is_carry_forward: false, is_active: true },
];

const BALANCES = [
  { leave_type_id: "lt-1", leave_type_name: "Annual Leave", leave_type_color: "#3b82f6", year: 2026, entitled_days: 20, carried_forward_days: 0, used_days: 2, pending_days: 0, remaining_days: 18 },
];

function renderWithClient(ui: React.ReactElement): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("LeaveScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(leaveService.listLeaveTypes).mockResolvedValue(TYPES);
    vi.mocked(leaveService.getMyLeaveBalances).mockResolvedValue(BALANCES);
    vi.mocked(leaveService.getMyLeaveRequests).mockResolvedValue([]);
  });

  it("shows the apply tab by default with leave types loaded", async () => {
    renderWithClient(<LeaveScreen />);
    await waitFor(() => expect(screen.getByRole("option", { name: "Annual Leave" })).toBeInTheDocument());
    expect(screen.getByTestId("leave-apply-form")).toBeInTheDocument();
  });

  it("shows the remaining balance once a leave type is picked", async () => {
    renderWithClient(<LeaveScreen />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("option", { name: "Annual Leave" })).toBeInTheDocument());
    await user.selectOptions(screen.getByTestId("leave-type-select"), "lt-1");
    expect(await screen.findByTestId("selected-type-balance")).toHaveTextContent("18 day(s) remaining");
  });

  it("submits a full-day leave request with the resolved dates", async () => {
    vi.mocked(leaveService.applyForLeave).mockResolvedValue({ id: "req-1" });
    renderWithClient(<LeaveScreen />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("option", { name: "Annual Leave" })).toBeInTheDocument());

    await user.selectOptions(screen.getByTestId("leave-type-select"), "lt-1");
    await user.click(screen.getByTestId("leave-submit-button"));

    await waitFor(() => expect(leaveService.applyForLeave).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(leaveService.applyForLeave).mock.calls[0]![0];
    expect(payload.leave_type_id).toBe("lt-1");
    expect(payload.duration_type).toBe("full_day");
    expect(payload.start_date).toBe(payload.end_date); // both default to today
    expect(screen.getByTestId("leave-success-message")).toBeInTheDocument();
  });

  it("switches to the history tab and lists past requests with a status badge", async () => {
    vi.mocked(leaveService.getMyLeaveRequests).mockResolvedValue([
      {
        id: "req-1", employee_id: "e-1", employee_name: "Ali", leave_type: "Annual Leave",
        leave_type_color: "#3b82f6", start_date: "2026-09-10", end_date: "2026-09-11",
        total_days: 2, duration_type: "full_day", half_day_period: null, hours: null,
        reason: "Family trip", status: "pending", created_at: "2026-09-01T00:00:00Z",
      },
    ]);
    renderWithClient(<LeaveScreen />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("leave-tab-history"));

    const list = await screen.findByTestId("leave-history-list");
    expect(list).toHaveTextContent("Annual Leave");
    expect(list).toHaveTextContent("pending");
    expect(list).toHaveTextContent("Family trip");
  });
});

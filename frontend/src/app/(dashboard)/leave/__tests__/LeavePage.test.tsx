/**
 * B-02 / B-03: a request can be cancelled from the list, and the Filter button
 * is no longer dead (leave type + date range reach the API).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LeavePage from "../page";

const REQUESTS = [
  { id: "r-pending", employee_id: "e1", employee_name: "Sara Khan", leave_type: "Annual", start_date: "2999-03-04", end_date: "2999-03-05", total_days: 2, reason: null, status: "pending", created_at: "2026-01-01T00:00:00Z" },
  { id: "r-approved-past", employee_id: "e1", employee_name: "Ali Raza", leave_type: "Sick", start_date: "2020-01-02", end_date: "2020-01-02", total_days: 1, reason: null, status: "approved", created_at: "2020-01-01T00:00:00Z" },
];

vi.mock("@/services/api-client", () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url === "/leave/types") return Promise.resolve({ data: { items: [{ id: "lt-sick", name: "Sick Leave" }, { id: "lt-annual", name: "Annual Leave" }] } });
      if (url === "/leave/requests") return Promise.resolve({ data: { items: REQUESTS, total: 2 } });
      return Promise.resolve({ data: {} });
    }),
    post: vi.fn().mockResolvedValue({ data: { status: "cancelled" } }),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import apiClient from "@/services/api-client";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}><LeavePage /></QueryClientProvider>);
}

describe("Leave page — cancel and filter", () => {
  beforeEach(() => vi.clearAllMocks());

  it("cancels a pending request", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Sara Khan");
    const buttons = screen.getAllByRole("button", { name: /cancel request/i });
    expect(buttons).toHaveLength(1);              // the approved leave that already started has no Cancel
    await user.click(buttons[0]!);
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith("/leave/requests/r-pending/cancel"));
  });

  it("Filter opens a panel and sends leave type and dates to the API", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Sara Khan");
    expect(screen.queryByTestId("leave-filters")).toBeNull();

    await user.click(screen.getByRole("button", { name: /^filter/i }));
    expect(screen.getByTestId("leave-filters")).toBeTruthy();

    await screen.findByRole("option", { name: "Sick Leave" });
    await user.selectOptions(screen.getByLabelText("Leave type"), "Sick Leave");
    await user.type(screen.getByLabelText("From date"), "2026-03-01");
    await user.type(screen.getByLabelText("To date"), "2026-03-31");

    await waitFor(() => {
      const calls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls.filter((c) => c[0] === "/leave/requests");
      const last = calls[calls.length - 1]![1].params;
      expect(last).toMatchObject({ leave_type_id: "lt-sick", date_from: "2026-03-01", date_to: "2026-03-31" });
    });
    expect(screen.getByRole("button", { name: /filter \(3\)/i })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /clear filters/i }));
    await waitFor(() => {
      const calls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls.filter((c) => c[0] === "/leave/requests");
      expect(calls[calls.length - 1]![1].params.leave_type_id).toBeUndefined();
    });
  });
});

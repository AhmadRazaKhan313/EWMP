/**
 * Regression tests for the "Leave completion" frontend piece (bug H6):
 * there used to be NO leave-request UI at all. These tests cover the new
 * ApplyLeaveModal — duration type switching (full/half/hourly), the
 * validation that mirrors the backend, and the exact payload shape sent
 * to POST /leave/requests for each duration type.
 *
 * Run:  cd frontend && npm test -- ApplyLeaveModal
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApplyLeaveModal } from "../ApplyLeaveModal";

const LEAVE_TYPES = [
  { id: "lt-annual", name: "Annual Leave", code: "AL", color: "#3b82f6", days_per_year: "20", is_paid: true },
  { id: "lt-sick", name: "Sick Leave", code: "SL", color: "#ef4444", days_per_year: "10", is_paid: true },
];

const BALANCES = [
  { leave_type_id: "lt-annual", leave_type_name: "Annual Leave", remaining_days: 12 },
  { leave_type_id: "lt-sick", leave_type_name: "Sick Leave", remaining_days: 10 },
];

vi.mock("@/services/api-client", () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url === "/leave/types") return Promise.resolve({ data: { items: LEAVE_TYPES } });
      if (url === "/leave/balances") return Promise.resolve({ data: { items: BALANCES } });
      return Promise.resolve({ data: {} });
    }),
    post: vi.fn().mockResolvedValue({ data: { id: "req-1", status: "pending" } }),
  },
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import apiClient from "@/services/api-client";

function renderModal(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return {
    onClose,
    ...render(
      <QueryClientProvider client={qc}>
        <ApplyLeaveModal open onClose={onClose} />
      </QueryClientProvider>,
    ),
  };
}

async function pickLeaveType(user: ReturnType<typeof userEvent.setup>, name = "Annual Leave") {
  await screen.findByText(name); // wait for the leave-types query to resolve and populate <option>s
  const select = screen.getByLabelText(/leave type/i);
  await user.selectOptions(select, name);
}

describe("ApplyLeaveModal (bug H6 — leave request UI)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders when open and lists real leave types from the API", async () => {
    renderModal();
    expect(await screen.findByText("Annual Leave")).toBeInTheDocument();
    expect(await screen.findByText("Sick Leave")).toBeInTheDocument();
  });

  it("shows the selected leave type's remaining balance", async () => {
    renderModal();
    const user = userEvent.setup();
    await pickLeaveType(user, "Sick Leave");
    await waitFor(() => expect(screen.getByLabelText(/leave type/i)).toHaveValue("lt-sick"));
    await waitFor(() => {
      const calls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0]);
      expect(calls).toContain("/leave/balances");
    });
    expect(await screen.findByText((content) => content.includes("remaining"))).toBeInTheDocument();
  });

  it("defaults to full-day and shows both Start Date and End Date fields", async () => {
    renderModal();
    expect(await screen.findByLabelText(/start date/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/end date/i)).toBeInTheDocument();
  });

  it("switching to half-day hides End Date and shows the AM/PM picker", async () => {
    renderModal();
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: /half day/i }));

    expect(screen.queryByLabelText(/end date/i)).not.toBeInTheDocument();
    expect(await screen.findByText(/which half/i)).toBeInTheDocument();
  });

  it("switching to hourly hides End Date and shows an hours input", async () => {
    renderModal();
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: /hourly/i }));

    expect(screen.queryByLabelText(/end date/i)).not.toBeInTheDocument();
    expect(await screen.findByLabelText(/hours/i)).toBeInTheDocument();
  });

  it("submits a full-day request with the entered start/end dates", async () => {
    renderModal();
    const user = userEvent.setup();
    await pickLeaveType(user);
    fireEvent.change(screen.getByLabelText(/start date/i), { target: { value: "2026-03-01" } });
    fireEvent.change(screen.getByLabelText(/end date/i), { target: { value: "2026-03-03" } });
    await user.click(screen.getByRole("button", { name: /submit request/i }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0] as [string, Record<string, unknown>];
    expect(payload).toMatchObject({
      leave_type_id: "lt-annual",
      duration_type: "full_day",
      start_date: "2026-03-01",
      end_date: "2026-03-03",
    });
  });

  it("submits a half-day request with end_date derived from start_date", async () => {
    renderModal();
    const user = userEvent.setup();
    await pickLeaveType(user);
    await user.click(screen.getByRole("radio", { name: /half day/i }));
    fireEvent.change(screen.getByLabelText(/date/i), { target: { value: "2026-03-01" } });
    await user.selectOptions(await screen.findByLabelText(/which half/i), "afternoon");
    await user.click(screen.getByRole("button", { name: /submit request/i }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0] as [string, Record<string, unknown>];
    expect(payload).toMatchObject({
      duration_type: "half_day",
      half_day_period: "afternoon",
      start_date: "2026-03-01",
      end_date: "2026-03-01",
    });
  });

  it("submits an hourly request with the numeric hours value", async () => {
    renderModal();
    const user = userEvent.setup();
    await pickLeaveType(user);
    await user.click(screen.getByRole("radio", { name: /hourly/i }));
    fireEvent.change(screen.getByLabelText(/date/i), { target: { value: "2026-03-01" } });
    fireEvent.change(await screen.findByLabelText(/hours/i), { target: { value: "3" } });
    await user.click(screen.getByRole("button", { name: /submit request/i }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0] as [string, Record<string, unknown>];
    expect(payload).toMatchObject({
      duration_type: "hourly",
      hours: 3,
      start_date: "2026-03-01",
      end_date: "2026-03-01",
    });
  });

  it("blocks submission when no leave type is selected", async () => {
    renderModal();
    const user = userEvent.setup();
    fireEvent.change(await screen.findByLabelText(/start date/i), { target: { value: "2026-03-01" } });
    fireEvent.change(screen.getByLabelText(/end date/i), { target: { value: "2026-03-01" } });
    await user.click(screen.getByRole("button", { name: /submit request/i }));

    expect(await screen.findByText(/^select a leave type$/i)).toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("blocks hourly submission when hours is left blank", async () => {
    renderModal();
    const user = userEvent.setup();
    await pickLeaveType(user);
    await user.click(screen.getByRole("radio", { name: /hourly/i }));
    fireEvent.change(await screen.findByLabelText(/date/i), { target: { value: "2026-03-01" } });
    await user.click(screen.getByRole("button", { name: /submit request/i }));

    expect(await screen.findByText(/enter the number of hours/i)).toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});

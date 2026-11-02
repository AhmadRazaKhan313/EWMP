/**
 * Admin attendance correction dialog (T-01 / T-02 / T-03): reason is
 * mandatory, the right API call is made for edit / mark / delete, and a
 * locked payroll shows the warning, with Override only for the owner.
 *
 * Run:  cd frontend && npm test -- AttendanceCorrectionDialog
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  AttendanceCorrectionDialog,
  correctionProblem,
  parseCorrectionError,
  type CorrectionRow,
} from "../AttendanceCorrectionDialog";

vi.mock("@/services/api-client", () => ({
  default: {
    get: vi.fn(), post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }), delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import apiClient from "@/services/api-client";

const api = apiClient as unknown as Record<"post" | "patch" | "delete", ReturnType<typeof vi.fn>>;
const existing: CorrectionRow = {
  employee_id: "e1", employee_name: "Dana Hire", employee_code: "EMP-1", record_id: "r1",
  status: "present", check_in: "2026-09-01T04:00:00Z", check_out: "2026-09-01T12:00:00Z",
};
const missing: CorrectionRow = { ...existing, record_id: null, status: "absent", check_in: null, check_out: null };

function show(row: CorrectionRow, onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={qc}><AttendanceCorrectionDialog row={row} date="2026-09-01" onClose={onClose} /></QueryClientProvider>);
  return onClose;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.post.mockResolvedValue({ data: {} });
  api.patch.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
});

describe("correctionProblem", () => {
  const v = { status: "", checkIn: "", checkOut: "", notes: "", reason: "" };
  it("needs a reason, valid times and at least one change", () => {
    expect(correctionProblem(false, v)).toMatch(/reason/i);
    expect(correctionProblem(false, { ...v, reason: "typo" })).toMatch(/at least one/i);
    expect(correctionProblem(false, { ...v, reason: "typo", checkIn: "9am" })).toMatch(/check-in/i);
    expect(correctionProblem(false, { ...v, reason: "typo", checkOut: "17:30" })).toBeNull();
  });
  it("marking a day needs a status, and both times for Present", () => {
    expect(correctionProblem(true, { ...v, reason: "sick" })).toMatch(/choose/i);
    expect(correctionProblem(true, { ...v, reason: "sick", status: "absent" })).toBeNull();
    expect(correctionProblem(true, { ...v, reason: "sick", status: "present", checkIn: "09:00" })).toMatch(/both/i);
    expect(correctionProblem(true, { ...v, reason: "sick", status: "present", checkIn: "09:00", checkOut: "17:00" })).toBeNull();
  });
});

describe("parseCorrectionError", () => {
  it("recognises the locked-payroll answer and whether it can be overridden", () => {
    const e = (can: boolean) => ({ response: { status: 409, data: { error: "PAYROLL_LOCKED", message: "locked", detail: { can_override: can } } } });
    expect(parseCorrectionError(e(true))).toMatchObject({ locked: true, canOverride: true });
    expect(parseCorrectionError(e(false))).toMatchObject({ locked: true, canOverride: false });
    expect(parseCorrectionError({ response: { data: { message: "boom" } } })).toMatchObject({ locked: false, message: "boom" });
  });
});

describe("dialog: existing day", () => {
  it("will not save without a reason", async () => {
    const user = userEvent.setup();
    show(existing);
    await user.type(screen.getByLabelText(/check-out/i), "16:00");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/reason/i);
    expect(api.patch).not.toHaveBeenCalled();
  });

  it("PATCHes only what changed, with the reason, then closes", async () => {
    const user = userEvent.setup();
    const onClose = show(existing);
    await user.type(screen.getByLabelText(/check-out/i), "16:00");
    await user.type(screen.getByLabelText(/reason/i), "Forgot to punch out");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith("/attendance/r1", { reason: "Forgot to punch out", check_out: "16:00" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("deleting asks to confirm, needs the reason, then DELETEs", async () => {
    const user = userEvent.setup();
    show(existing);
    await user.click(screen.getByRole("button", { name: /delete day/i }));
    await user.click(screen.getByRole("button", { name: /confirm delete/i }));
    expect(api.delete).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText(/reason/i), "Duplicate entry");
    await user.click(screen.getByRole("button", { name: /confirm delete/i }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/attendance/r1", { params: { reason: "Duplicate entry" } }));
  });

  it("a locked payroll shows the warning, and the owner can override", async () => {
    const user = userEvent.setup();
    api.patch
      .mockRejectedValueOnce({ response: { status: 409, data: { error: "PAYROLL_LOCKED", message: "The payroll \"Sep\" is locked", detail: { can_override: true } } } })
      .mockResolvedValueOnce({ data: {} });
    show(existing);
    await user.type(screen.getByLabelText(/check-out/i), "16:00");
    await user.type(screen.getByLabelText(/reason/i), "late fix");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/is locked/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /override the lock/i }));
    await waitFor(() => expect(api.patch).toHaveBeenLastCalledWith("/attendance/r1",
      { reason: "late fix", check_out: "16:00", override_payroll_lock: true }));
  });

  it("someone who cannot override sees the warning but no Override button", async () => {
    const user = userEvent.setup();
    api.patch.mockRejectedValueOnce({ response: { status: 409, data: { error: "PAYROLL_LOCKED", message: "locked", detail: { can_override: false } } } });
    show(existing);
    await user.type(screen.getByLabelText(/check-out/i), "16:00");
    await user.type(screen.getByLabelText(/reason/i), "late fix");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("locked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /override/i })).toBeNull();
  });
});

describe("dialog: day with no record", () => {
  it("marks the employee absent on their behalf", async () => {
    const user = userEvent.setup();
    show(missing);
    expect(screen.getByRole("dialog", { name: /mark attendance/i })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/mark as/i), "absent");
    await user.type(screen.getByLabelText(/reason/i), "Called in sick");
    await user.click(screen.getByRole("button", { name: "Mark" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/attendance", null, {
      params: { employee_id: "e1", date: "2026-09-01", attendance_status: "absent", reason: "Called in sick" },
    }));
  });

  it("marks present with both times", async () => {
    const user = userEvent.setup();
    show(missing);
    await user.selectOptions(screen.getByLabelText(/mark as/i), "present");
    await user.type(screen.getByLabelText(/check-in/i), "09:00");
    await user.type(screen.getByLabelText(/check-out/i), "17:00");
    await user.type(screen.getByLabelText(/reason/i), "Laptop was down");
    await user.click(screen.getByRole("button", { name: "Mark" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/attendance", null, {
      params: { employee_id: "e1", date: "2026-09-01", attendance_status: "present", reason: "Laptop was down", check_in: "09:00", check_out: "17:00" },
    }));
  });
});

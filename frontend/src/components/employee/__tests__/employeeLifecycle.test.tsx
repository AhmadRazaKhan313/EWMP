/**
 * E-07 / E-08 UI: offboarding dialog, status timeline, contracts tab.
 *
 * Run:  cd frontend && npm test -- employeeLifecycle
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OffboardDialog } from "../OffboardDialog";
import { StatusTimeline } from "../StatusTimeline";
import { ContractsPanel } from "../ContractsPanel";

vi.mock("@/services/api-client", () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import apiClient from "@/services/api-client";

const api = apiClient as unknown as Record<"get" | "post" | "patch" | "delete", ReturnType<typeof vi.fn>>;
const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

beforeEach(() => {
  vi.clearAllMocks();
  api.post.mockResolvedValue({ data: {} });
  api.patch.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
});

describe("OffboardDialog", () => {
  it("stays disabled until a reason is written and the warning is confirmed, then calls the API", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    wrap(<OffboardDialog employeeId="e1" employeeName="Dana Hire" open onClose={onClose} />);
    const go = screen.getByRole("button", { name: "Offboard" });
    expect((go as HTMLButtonElement).disabled).toBe(true);
    await user.type(screen.getByLabelText("Details (required)"), "Moving abroad");
    expect((go as HTMLButtonElement).disabled).toBe(true); // still needs the confirmation
    await user.click(screen.getByLabelText(/I understand/));
    await user.selectOptions(screen.getByLabelText("Reason for leaving"), "termination");
    expect((go as HTMLButtonElement).disabled).toBe(false);
    await user.click(go);
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, body, config] = api.post.mock.calls[0]!;
    expect(url).toBe("/employees/e1/offboard");
    expect(body).toBeNull();
    expect(config.params).toMatchObject({ exit_reason: "Moving abroad", reason_type: "termination" });
    expect(config.params.date_of_leaving).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("renders nothing while closed", () => {
    wrap(<OffboardDialog employeeId="e1" employeeName="Dana" open={false} onClose={() => {}} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("StatusTimeline", () => {
  it("lists changes newest first with who and why", async () => {
    api.get.mockResolvedValue({ data: [
      { id: "2", from_status: "active", to_status: "resigned", reason: "resignation: Moving abroad", effective_date: "2026-03-01", source: "offboard", changed_by: "Owner Test", created_at: null },
      { id: "1", from_status: null, to_status: "active", reason: null, effective_date: "2026-01-01", source: "created", changed_by: null, created_at: null },
    ] });
    wrap(<StatusTimeline employeeId="e1" />);
    expect(await screen.findByText("Active → Resigned")).toBeTruthy();
    expect(screen.getByText(/by Owner Test/)).toBeTruthy();
    expect(screen.getByText("resignation: Moving abroad")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("/employees/e1/history");
  });

  it("says so when nothing is recorded", async () => {
    api.get.mockResolvedValue({ data: [] });
    wrap(<StatusTimeline employeeId="e1" />);
    expect(await screen.findByText("No status changes recorded yet.")).toBeTruthy();
  });
});

const contract = (over = {}) => ({
  id: "c1", employee_id: "e1", employee_code: "EMP-1", employee_name: "Dana Hire", contract_type: "fixed_term",
  start_date: "2026-01-01", end_date: "2026-12-31", status: "active", state: "expiring", days_left: 12,
  renewal_alert_days: 30, document_id: null, notes: null, renewed_from_id: null, ...over,
});
const list = (items: unknown[]) => ({ data: { items, total: items.length, page: 1, page_size: 200, total_pages: 1 } });

describe("ContractsPanel", () => {
  it("shows the state, and offers renew / edit / terminate for an active contract", async () => {
    api.get.mockResolvedValue(list([contract()]));
    wrap(<ContractsPanel employeeId="e1" canManage />);
    expect(await screen.findByText(/Expiring soon · 12d/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Renew/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Terminate/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Add contract/ })).toBeNull(); // one active contract at a time
  });

  it("is read-only without permission", async () => {
    api.get.mockResolvedValue(list([contract()]));
    wrap(<ContractsPanel employeeId="e1" canManage={false} />);
    await screen.findByText(/Expiring soon/);
    expect(screen.queryByRole("button", { name: /Renew/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Add contract/ })).toBeNull();
  });

  it("adds a contract: end date is required unless permanent", async () => {
    const user = userEvent.setup();
    api.get.mockResolvedValue(list([]));
    wrap(<ContractsPanel employeeId="e1" canManage />);
    await user.click(await screen.findByRole("button", { name: /Add contract/ }));
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    await user.type(screen.getByLabelText("Start date"), "2026-02-01");
    expect(save.disabled).toBe(true); // fixed term with no end date
    await user.type(screen.getByLabelText("End date"), "2026-01-01");
    expect(save.disabled).toBe(true); // end before start
    await user.clear(screen.getByLabelText("End date"));
    await user.type(screen.getByLabelText("End date"), "2027-01-31");
    expect(save.disabled).toBe(false);
    await user.click(save);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/employees/e1/contracts", expect.objectContaining({
      contract_type: "fixed_term", start_date: "2026-02-01", end_date: "2027-01-31", renewal_alert_days: 30,
    })));
  });

  it("permanent contracts hide the end date and send null", async () => {
    const user = userEvent.setup();
    api.get.mockResolvedValue(list([]));
    wrap(<ContractsPanel employeeId="e1" canManage />);
    await user.click(await screen.findByRole("button", { name: /Add contract/ }));
    await user.selectOptions(screen.getByLabelText("Contract type"), "permanent");
    expect(screen.queryByLabelText("End date")).toBeNull();
    await user.type(screen.getByLabelText("Start date"), "2026-02-01");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/employees/e1/contracts", expect.objectContaining({ end_date: null })));
  });

  it("renew starts the day after the old end date and posts to the renew endpoint", async () => {
    const user = userEvent.setup();
    api.get.mockResolvedValue(list([contract()]));
    wrap(<ContractsPanel employeeId="e1" canManage />);
    await user.click(await screen.findByRole("button", { name: /Renew/ }));
    expect((screen.getByLabelText("Start date") as HTMLInputElement).value).toBe("2027-01-01");
    await user.type(screen.getByLabelText("End date"), "2027-12-31");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/employees/contracts/c1/renew", expect.objectContaining({
      start_date: "2027-01-01", end_date: "2027-12-31",
    })));
  });

  it("terminate asks for confirmation first", async () => {
    const user = userEvent.setup();
    api.get.mockResolvedValue(list([contract()]));
    wrap(<ContractsPanel employeeId="e1" canManage />);
    await user.click(await screen.findByRole("button", { name: /Terminate/ }));
    expect(api.post).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Reason (optional)"), "Project cancelled");
    await user.click(screen.getByRole("button", { name: "Confirm terminate" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/employees/contracts/c1/terminate", { reason: "Project cancelled" }));
  });

  it("old contracts show a Delete button but no renew", async () => {
    api.get.mockResolvedValue(list([contract({ status: "renewed", state: "renewed", days_left: null })]));
    wrap(<ContractsPanel employeeId="e1" canManage />);
    expect(await screen.findByText("Renewed")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Renew/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Delete/ })).toBeTruthy();
  });
});

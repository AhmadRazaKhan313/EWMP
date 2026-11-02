/** Settings → Break: org default, pending unlock requests, approve/deny. Run: npm test -- BreakSettings */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/store/auth.store", () => ({
  useAuthStore: (sel: (s: { hasPermission: () => boolean }) => unknown) => sel({ hasPermission: () => true }),
}));
vi.mock("@/services/api-client", () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
import apiClient from "@/services/api-client";
import { BreakSettings } from "../BreakSettings";

const api = apiClient as unknown as Record<"get" | "post" | "put" | "delete", ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  api.post.mockResolvedValue({ data: {} });
  api.put.mockResolvedValue({ data: {} });
  api.get.mockImplementation(async (url: string) => {
    if (url === "/break/policies") return { data: [
      { id: "p0", scope: "organization", scope_id: null, start_time: "13:00", duration_minutes: 60, days: null, is_active: true },
      { id: "p1", scope: "department", scope_id: "d1", start_time: "12:30", duration_minutes: 45, days: null, is_active: true }] };
    if (url === "/break/overrides") return { data: [] };
    if (url === "/break/unlock-requests") return { data: { pending_count: 1, items: [
      { id: "r1", employee_name: "Sara Khan", employee_code: "EMP-7", break_date: "2026-11-02", reason: "Deadline", status: "pending" }] } };
    if (url === "/departments") return { data: { items: [{ id: "d1", name: "Engineering" }] } };
    if (url === "/shifts") return { data: { items: [] } };
    if (url === "/employees") return { data: { items: [{ id: "e1", full_name: "Sara Khan", employee_code: "EMP-7" }] } };
    return { data: {} };
  });
});

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><BreakSettings /></QueryClientProvider>);
}

describe("break settings", () => {
  it("lists pending requests and approves one", async () => {
    show();
    expect(await screen.findByText("Deadline")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/break/unlock-requests/r1/approve"));
  });

  it("denies a request", async () => {
    show();
    await screen.findByText("Deadline");
    await userEvent.click(screen.getByRole("button", { name: /deny/i }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/break/unlock-requests/r1/deny"));
  });

  it("saves the org default", async () => {
    show();
    const dur = await screen.findByLabelText("Duration");
    await waitFor(() => expect((dur as HTMLInputElement).value).toBe("60"));
    await userEvent.clear(dur);
    await userEvent.type(dur, "45");
    await userEvent.click(screen.getByRole("button", { name: "Save default" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/break/policy",
      expect.objectContaining({ start_time: "13:00", duration_minutes: 45, days: null, is_active: true })));
  });

  it("shows group rules with the department name and deletes one", async () => {
    show();
    expect((await screen.findAllByText("Engineering")).length).toBeGreaterThan(1);
    await userEvent.click(screen.getByLabelText("Delete rule"));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/break/policies/p1"));
  });
});

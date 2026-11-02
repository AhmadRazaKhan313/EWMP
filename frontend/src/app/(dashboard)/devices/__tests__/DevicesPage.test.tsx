/**
 * Devices page: leads with the employee, shows no device telemetry, and has Lock /
 * Restart / Shutdown buttons at the top that act on the ticked employees.
 *
 * Run:  cd frontend && npm test -- DevicesPage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/services/api-client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
import apiClient from "@/services/api-client";
import DevicesPage from "../page";

const api = apiClient as unknown as { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn> };
const dev = (over = {}) => ({
  id: "d1", hostname: "DESKTOP-I0292P0", device_name: "DESKTOP-I0292P0", os_type: "windows", os_name: "Windows 11",
  os_version: "23H2", status: "online", last_seen_at: new Date().toISOString(), health_score: 90,
  cpu_usage_percent: 12, ram_usage_percent: 40, disk_usage_percent: 50, assigned_employee_id: "e1",
  assigned_employee: { id: "e1", full_name: "Sara Khan", employee_code: "EMP-0042", email: "s@x.com", phone: null, avatar_url: null, department: "Engineering", designation: "Developer" },
  public_ip: "1.2.3.4", local_ip: "10.0.0.2", ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  window.history.pushState({}, "", "/devices");
  window.confirm = vi.fn(() => true);
  api.post.mockResolvedValue({ data: {} });
  api.get.mockResolvedValue({ data: { items: [dev(), dev({ id: "d2", hostname: "SPARE-PC", status: "offline", assigned_employee_id: null, assigned_employee: null })], total: 2 } });
});

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><DevicesPage /></QueryClientProvider>);
}

describe("devices page", () => {
  it("leads with the employee and shows no device telemetry", async () => {
    show();
    expect(await screen.findByText("Sara Khan")).toBeTruthy();
    expect(screen.getByText("EMP-0042")).toBeTruthy();
    expect(screen.getByText("Engineering")).toBeTruthy();
    expect(screen.getByText("Developer")).toBeTruthy();
    expect(screen.getByText("Unassigned")).toBeTruthy();
    for (const gone of ["Health", "CPU", "RAM", "IP"]) expect(screen.queryByText(gone)).toBeNull();
    expect(screen.queryByText("10.0.0.2")).toBeNull();
  });

  it("has no Enroll / Add device button any more", async () => {
    show();
    await screen.findByText("Sara Khan");
    expect(screen.queryByText(/enroll/i)).toBeNull();
    expect(screen.queryByText(/add device/i)).toBeNull();
  });

  it("has Lock / Restart / Shutdown at the top, disabled until someone is ticked", async () => {
    show();
    await screen.findByText("Sara Khan");
    for (const name of [/^Lock/, /^Restart/, /^Shutdown/]) {
      expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it("locks every ticked employee's computer", async () => {
    const user = userEvent.setup();
    show();
    await screen.findByText("Sara Khan");
    await user.click(screen.getByLabelText("Select Sara Khan"));
    await user.click(screen.getByRole("button", { name: /^Lock \(1\)/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/devices/d1/actions/lock"));
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it("select-all then Shutdown hits every device, and asks first", async () => {
    const user = userEvent.setup();
    show();
    await screen.findByText("Sara Khan");
    await user.click(screen.getByLabelText("Select all"));
    await user.click(screen.getByRole("button", { name: /^Shutdown \(2\)/ }));
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    expect(api.post).toHaveBeenCalledWith("/devices/d2/actions/shutdown");
  });

  it("does nothing when the confirmation is declined", async () => {
    window.confirm = vi.fn(() => false);
    const user = userEvent.setup();
    show();
    await screen.findByText("Sara Khan");
    await user.click(screen.getByLabelText("Select Sara Khan"));
    await user.click(screen.getByRole("button", { name: /^Restart/ }));
    expect(api.post).not.toHaveBeenCalled();
  });

  it("ticking a box does not open the device page, clicking the row does", async () => {
    const user = userEvent.setup();
    show();
    await screen.findByText("Sara Khan");
    await user.click(screen.getByLabelText("Select Sara Khan"));
    expect(push).not.toHaveBeenCalled();
    await user.click(screen.getByText("Sara Khan"));
    expect(push).toHaveBeenCalledWith("/devices/d1");
  });

  it("sends an old /devices?device_id=…&tab=alerts link to the device page", async () => {
    window.history.pushState({}, "", "/devices?device_id=d1&tab=alerts");
    show();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/devices/d1?tab=alerts"));
  });
});

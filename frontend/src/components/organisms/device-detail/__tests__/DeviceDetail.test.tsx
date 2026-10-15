import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { push, decommission, device, mut } = vi.hoisted(() => {
  const push = vi.fn();
  const decommission = vi.fn().mockResolvedValue({});
  const device = {
    id: "d1", hostname: "PC-01", device_name: "Front desk", status: "online", health_score: 90, health_issues: [],
    last_seen_at: new Date().toISOString(), os_type: "windows", os_name: "Windows", os_version: "11", cpu_model: "i5", cpu_cores: 4,
    ram_total_gb: 8, disk_total_gb: 256, gpu_model: null, local_ip: "10.0.0.2", public_ip: null, mac_address: null,
    serial_number: null, asset_tag: null, agent_version: "1", assigned_employee: null, latest_metric: null,
  };
  const mut = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  return { push, decommission, device, mut };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/services/employee.service", () => ({ useEmployees: () => ({ data: { items: [] } }) }));

vi.mock("@/services/devices.service", () => ({
  useDevice: () => ({ data: device, isLoading: false, isError: false }),
  useDeviceMetrics: () => ({ data: [] }), useDeviceProcesses: () => ({ data: undefined }),
  useDeviceScreenshots: () => ({ data: [] }), useDeviceAlerts: () => ({ data: [] }),
  useAllowedApps: () => ({ data: [] }), useActivityWatchlist: () => ({ data: [] }),
  useScreenshotImage: () => ({ data: null, isLoading: false }),
  useRequestScreenshot: mut, useAcknowledgeAlert: mut, useAddAllowedApp: mut, useRemoveAllowedApp: mut,
  useAssignDevice: mut, useUnassignDevice: mut, useDeviceAction: mut, useMessageDevice: mut,
  useDecommissionDevice: () => ({ mutateAsync: decommission, mutate: vi.fn(), isPending: false }),
}));

import { DeviceDetail } from "../DeviceDetail";

describe("DeviceDetail page", () => {
  beforeEach(() => { push.mockClear(); decommission.mockClear(); });

  it("shows the device and switches sections", () => {
    render(<DeviceDetail deviceId="d1" />);
    expect(screen.getByRole("heading", { name: "Front desk" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Device overview" })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Alerts section"));
    expect(screen.getByRole("heading", { name: "Flagged activity" })).toBeInTheDocument();
    expect(screen.getByText(/No flagged activity/)).toBeInTheDocument();
  });

  it("decommission confirms, calls the API and returns to the list", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DeviceDetail deviceId="d1" />);
    fireEvent.click(screen.getByRole("button", { name: /decommission/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/devices"));
    expect(decommission).toHaveBeenCalled();
  });

  it("does nothing when decommission is cancelled", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<DeviceDetail deviceId="d1" />);
    fireEvent.click(screen.getByRole("button", { name: /decommission/i }));
    expect(decommission).not.toHaveBeenCalled();
  });
});

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./api-client";
import type { DeviceDetail, DeviceMetricPoint, DeviceProcess, DeviceScreenshotItem, DeviceAlertItem, RecentAlertItem, AllowedAppItem } from "@/types";

export const deviceKeys = {
  all: ["devices"] as const,
  list: () => [...deviceKeys.all, "list"] as const,
  detail: (id: string) => [...deviceKeys.all, "detail", id] as const,
  metrics: (id: string, hours: number) => [...deviceKeys.all, "metrics", id, hours] as const,
  processes: (id: string) => [...deviceKeys.all, "processes", id] as const,
  allowedApps: (id: string) => [...deviceKeys.all, "allowed-apps", id] as const,
  watchlist: () => [...deviceKeys.all, "watchlist"] as const,
  screenshots: (id: string) => [...deviceKeys.all, "screenshots", id] as const,
  alerts: (id: string) => [...deviceKeys.all, "alerts", id] as const,
  recentAlerts: () => [...deviceKeys.all, "recent-alerts"] as const,
};

async function fetchDevice(id: string) {
  const { data } = await apiClient.get<DeviceDetail>(`/devices/${id}`);
  return data;
}

export function useDevice(deviceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: deviceKeys.detail(deviceId ?? ""),
    queryFn: () => fetchDevice(deviceId as string),
    enabled: !!deviceId && enabled,
    refetchInterval: 30_000,
  });
}

async function fetchDeviceMetrics(id: string, hours: number) {
  const { data } = await apiClient.get<{ device_id: string; points: DeviceMetricPoint[] }>(
    `/devices/${id}/metrics`,
    { params: { hours } },
  );
  return data.points;
}

export function useDeviceMetrics(deviceId: string | undefined, hours = 24, enabled = true) {
  return useQuery({
    queryKey: deviceKeys.metrics(deviceId ?? "", hours),
    queryFn: () => fetchDeviceMetrics(deviceId as string, hours),
    enabled: !!deviceId && enabled,
  });
}

async function fetchDeviceProcesses(id: string) {
  const { data } = await apiClient.get<{ captured_at: string | null; processes: DeviceProcess[] }>(
    `/devices/${id}/processes`,
  );
  return data;
}

export function useDeviceProcesses(deviceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: deviceKeys.processes(deviceId ?? ""),
    queryFn: () => fetchDeviceProcesses(deviceId as string),
    enabled: !!deviceId && enabled,
  });
}

async function fetchDeviceScreenshots(id: string) {
  const { data } = await apiClient.get<{ items: DeviceScreenshotItem[]; total: number }>(
    `/devices/${id}/screenshots`,
  );
  return data.items;
}

export function useDeviceScreenshots(deviceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: deviceKeys.screenshots(deviceId ?? ""),
    queryFn: () => fetchDeviceScreenshots(deviceId as string),
    enabled: !!deviceId && enabled,
    refetchInterval: enabled ? 10_000 : false,
  });
}

export function useRequestScreenshot(deviceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await apiClient.post(`/devices/${deviceId}/screenshot/request`);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: deviceKeys.screenshots(deviceId) }),
  });
}

// The image endpoint requires the same Bearer auth as everything else, so
// a plain <img src="..."> can't be used directly — the browser wouldn't
// attach the Authorization header. Fetch as a blob (same pattern as
// downloadEmployeeDocument) and hand back an object URL instead.
export function useScreenshotImage(deviceId: string, screenshotId: string | null) {
  return useQuery({
    queryKey: [...deviceKeys.screenshots(deviceId), screenshotId, "image"],
    queryFn: async () => {
      const response = await apiClient.get(
        `/devices/${deviceId}/screenshots/${screenshotId}/image`,
        { responseType: "blob" },
      );
      return URL.createObjectURL(new Blob([response.data]));
    },
    enabled: !!screenshotId,
    staleTime: Infinity, // a captured screenshot never changes — no need to refetch
    gcTime: 5 * 60 * 1000,
  });
}

function useInvalidateDevice(deviceId: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: deviceKeys.detail(deviceId) });
    void qc.invalidateQueries({ queryKey: deviceKeys.list() });
  };
}

export function useAssignDevice(deviceId: string) {
  const invalidate = useInvalidateDevice(deviceId);
  return useMutation({
    mutationFn: async (employeeId: string) => {
      await apiClient.post(`/devices/${deviceId}/assign`, { employee_id: employeeId });
    },
    onSuccess: invalidate,
  });
}

export function useUnassignDevice(deviceId: string) {
  const invalidate = useInvalidateDevice(deviceId);
  return useMutation({
    mutationFn: async () => {
      await apiClient.post(`/devices/${deviceId}/unassign`);
    },
    onSuccess: invalidate,
  });
}

export function useUpdateDevice(deviceId: string) {
  const invalidate = useInvalidateDevice(deviceId);
  return useMutation({
    mutationFn: async (body: { device_name?: string; notes?: string; asset_tag?: string }) => {
      await apiClient.patch(`/devices/${deviceId}`, body);
    },
    onSuccess: invalidate,
  });
}

export function useDeviceAction(deviceId: string) {
  const invalidate = useInvalidateDevice(deviceId);
  return useMutation({
    mutationFn: async (action: "lock" | "restart" | "shutdown") => {
      await apiClient.post(`/devices/${deviceId}/actions/${action}`);
    },
    onSuccess: invalidate,
  });
}

export function useMessageDevice(deviceId: string) {
  return useMutation({
    mutationFn: async (message: string) => {
      await apiClient.post(`/devices/${deviceId}/actions/message`, { message });
    },
  });
}

export function useDecommissionDevice(deviceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await apiClient.post(`/devices/${deviceId}/decommission`);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: deviceKeys.list() });
    },
  });
}

// ── Activity Alerts ─────────────────────────────────────────────────────────
async function fetchDeviceAlerts(id: string) {
  const { data } = await apiClient.get<{ items: DeviceAlertItem[]; total: number }>(
    `/devices/${id}/alerts`,
  );
  return data.items;
}

export function useDeviceAlerts(deviceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: deviceKeys.alerts(deviceId ?? ""),
    queryFn: () => fetchDeviceAlerts(deviceId as string),
    enabled: !!deviceId && enabled,
    refetchInterval: enabled ? 15_000 : false,
  });
}

export function useAcknowledgeAlert(deviceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (alertId: string) => {
      await apiClient.post(`/devices/${deviceId}/alerts/${alertId}/acknowledge`);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: deviceKeys.alerts(deviceId) });
      void qc.invalidateQueries({ queryKey: deviceKeys.recentAlerts() });
    },
  });
}

// Org-wide feed, used by the dashboard notification indicator — polls so
// a newly-raised alert appears without a manual refresh, mirroring the
// same near-real-time pattern used for screenshots above.
async function fetchRecentAlerts(sinceMinutes: number) {
  const { data } = await apiClient.get<{ items: RecentAlertItem[]; total: number }>(
    "/devices/alerts/recent",
    { params: { since_minutes: sinceMinutes } },
  );
  return data.items;
}

export function useRecentDeviceAlerts(sinceMinutes = 60) {
  return useQuery({
    queryKey: [...deviceKeys.recentAlerts(), sinceMinutes],
    queryFn: () => fetchRecentAlerts(sinceMinutes),
    refetchInterval: 20_000,
  });
}

// ── Fleet-scale Alerts Inbox ─────────────────────────────────────────────────
// The paginated, filterable screen — what an admin actually uses once
// there are hundreds/thousands of devices, instead of opening every
// device's drawer one at a time to check for alerts.
export interface AlertsInboxFilters {
  page?: number;
  page_size?: number;
  alert_type?: "flagged_app_usage" | "flagged_browsing";
  is_acknowledged?: boolean;
  device_id?: string;
  days?: number;
}

export interface AlertsInboxResponse {
  items: RecentAlertItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  unacknowledged_count: number;
}

async function fetchAlertsInbox(filters: AlertsInboxFilters) {
  const { data } = await apiClient.get<AlertsInboxResponse>("/devices/alerts", { params: filters });
  return data;
}

export function useAlertsInbox(filters: AlertsInboxFilters) {
  return useQuery({
    queryKey: [...deviceKeys.all, "inbox", filters],
    queryFn: () => fetchAlertsInbox(filters),
    refetchInterval: 15_000,
  });
}

export function useBulkAcknowledgeAlerts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (alertIds: string[]) => {
      const { data } = await apiClient.post<{ acknowledged: number }>(
        "/devices/alerts/acknowledge-bulk",
        { alert_ids: alertIds },
      );
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: deviceKeys.all });
    },
  });
}

// ── Per-Device Allow-List (overrides the global watch-list) ────────────────
async function fetchActivityWatchlist() {
  const { data } = await apiClient.get<{ watchlist: string[] }>("/devices/activity-watchlist");
  return data.watchlist;
}

export function useActivityWatchlist() {
  return useQuery({
    queryKey: deviceKeys.watchlist(),
    queryFn: fetchActivityWatchlist,
    staleTime: 5 * 60 * 1000, // rarely changes
  });
}

async function fetchAllowedApps(deviceId: string) {
  const { data } = await apiClient.get<{ items: AllowedAppItem[]; total: number }>(
    `/devices/${deviceId}/allowed-apps`,
  );
  return data.items;
}

export function useAllowedApps(deviceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: deviceKeys.allowedApps(deviceId ?? ""),
    queryFn: () => fetchAllowedApps(deviceId as string),
    enabled: !!deviceId && enabled,
  });
}

export function useAddAllowedApp(deviceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: { domain_or_app: string; reason?: string }) => {
      const { data } = await apiClient.post<{ id: string; domain_or_app: string }>(
        `/devices/${deviceId}/allowed-apps`,
        input,
      );
      return data;
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: deviceKeys.allowedApps(deviceId) }),
  });
}

export function useRemoveAllowedApp(deviceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (allowedAppId: string) => {
      await apiClient.delete(`/devices/${deviceId}/allowed-apps/${allowedAppId}`);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: deviceKeys.allowedApps(deviceId) }),
  });
}

import axios from "axios";
import apiClient from "@shared/api-client";
import { getServerUrl } from "@shared/api-client";
import type { HardwareInfo, HeartbeatResponse, WatchlistAlert } from "@shared/deviceTypes";

export interface SelfEnrollResult {
  device_id: string;
  agent_token: string;
}

export const deviceService = {
  /** Delegates to the main process (see main/hardwareInfo.ts) — the
   * renderer has no Node `os` access itself. */
  getHardwareInfo: (): Promise<HardwareInfo> => window.ewmp.device.getHardwareInfo(),

  /** Mirrors agent/ewmp_agent.py's enroll(), but authenticated with the
   * employee's own access token (apiClient already attaches it) rather
   * than a separate admin-issued enrollment_token — see backend's
   * POST /devices/self-enroll. consent_acknowledged is always sent as
   * true: this is only ever called after ConsentNotice's click, never
   * speculatively. */
  selfEnroll: async (hardware: HardwareInfo): Promise<SelfEnrollResult> =>
    (
      await apiClient.post<SelfEnrollResult>("/devices/self-enroll", {
        ...hardware,
        consent_acknowledged: true,
      })
    ).data,

  /**
   * POST /devices/heartbeat — keeps the admin Devices table's online/
   * offline status live (see useDeviceHeartbeat.ts for the polling loop
   * and backend/app/workers/tasks/device_health.py for how a device gets
   * flipped back to OFFLINE once heartbeats stop).
   *
   * Deliberately does NOT go through the shared `apiClient`: its request
   * interceptor unconditionally overwrites the Authorization header with
   * the signed-in EMPLOYEE's access token (see api-client.ts line ~104)
   * — there is no per-request way to override that once it's wired in.
   * But POST /devices/heartbeat authenticates via `get_current_device`,
   * which expects the DEVICE's own agent_token (issued once by
   * self-enroll and stored under the "agentToken" secureStore key), not
   * a user JWT. Sending the employee's token here would fail every
   * single heartbeat with 401 "Invalid or expired agent token" — so this
   * uses a bare axios call with an explicitly-built Authorization header
   * instead of the shared client.
   *
   * No body fields sent yet — every field on HeartbeatRequest is
   * optional; CPU/RAM/disk metrics are Track B step 3, not yet built.
   *
   * Returns the response body (`actions`, `activity_watchlist`) rather
   * than discarding it — see backend's heartbeat() docstring: "metrics
   * in, pending actions out". Returns null (never throws) if enrollment
   * hasn't produced an agentToken yet, since useDeviceHeartbeat only
   * calls this once deviceStatus is "enrolled" but a defensive check
   * here costs nothing.
   */
  sendHeartbeat: async (): Promise<HeartbeatResponse | null> => {
    const agentToken = await window.ewmp.secureStore.get("agentToken");
    if (!agentToken) return null;

    const serverUrl = await getServerUrl();
    const { data } = await axios.post<HeartbeatResponse>(
      `${serverUrl}/devices/heartbeat`,
      {},
      { headers: { Authorization: `Bearer ${agentToken}` }, timeout: 15_000 },
    );
    return data;
  },

  /**
   * POST /devices/screenshots/upload — fulfils a queued "screenshot"
   * action from the heartbeat response. Same agent_token auth as
   * sendHeartbeat (not the employee's session token) — this endpoint
   * authenticates via get_current_device too.
   */
  uploadScreenshot: async (
    base64Png: string,
    meta: { width: number; height: number; requestedBy?: string },
  ): Promise<void> => {
    const agentToken = await window.ewmp.secureStore.get("agentToken");
    if (!agentToken) return;

    const bytes = Uint8Array.from(atob(base64Png), (c) => c.charCodeAt(0));
    const form = new FormData();
    form.append("file", new Blob([bytes], { type: "image/png" }), "screenshot.png");
    form.append("mime_type", "image/png");
    form.append("width", String(meta.width));
    form.append("height", String(meta.height));
    if (meta.requestedBy) form.append("requested_by", meta.requestedBy);

    const serverUrl = await getServerUrl();
    await axios.post(`${serverUrl}/devices/screenshots/upload`, form, {
      headers: { Authorization: `Bearer ${agentToken}` },
      timeout: 30_000,
    });
  },

  /**
   * POST /devices/alerts/upload — reports flagged app/window matches
   * already filtered locally against the activity_watchlist (see
   * DeviceAlert's backend docstring: this endpoint "does not accept...
   * a full activity/browsing log entry", only pre-matched items).
   */
  uploadAlerts: async (
    alerts: WatchlistAlert[],
  ): Promise<{ created: number; suppressed_by_allowlist: number } | null> => {
    const agentToken = await window.ewmp.secureStore.get("agentToken");
    if (!agentToken || alerts.length === 0) return null;

    const serverUrl = await getServerUrl();
    const { data } = await axios.post(
      `${serverUrl}/devices/alerts/upload`,
      { alerts },
      { headers: { Authorization: `Bearer ${agentToken}` }, timeout: 15_000 },
    );
    return data;
  },
};

import axios from "axios";
import apiClient from "@shared/api-client";
import { getServerUrl } from "@shared/api-client";
import type { HardwareInfo } from "@shared/deviceTypes";

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
   * A no-op (never throws) if enrollment hasn't produced an agentToken
   * yet, since useDeviceHeartbeat only calls this once deviceStatus is
   * "enrolled" but a defensive check here costs nothing.
   */
  sendHeartbeat: async (): Promise<void> => {
    const agentToken = await window.ewmp.secureStore.get("agentToken");
    if (!agentToken) return;

    const serverUrl = await getServerUrl();
    await axios.post(
      `${serverUrl}/devices/heartbeat`,
      {},
      { headers: { Authorization: `Bearer ${agentToken}` }, timeout: 15_000 },
    );
  },
};

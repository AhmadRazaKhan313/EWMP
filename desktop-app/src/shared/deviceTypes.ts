/**
 * Shape sent to POST /devices/self-enroll (minus consent_acknowledged,
 * which the renderer adds once the employee has clicked through
 * ConsentNotice — see backend's SelfEnrollRequest for the authoritative
 * field list this must stay in sync with).
 */
export type DeviceOsType = "windows" | "linux" | "macos" | "android" | "ios" | "other";

/** Tray icon/status states — see main/trayIcons.ts for the actual icon
 * assets. Lives here (not in main/) so preload can reference the type
 * without a cross-process relative import. */
export type TrayIconStatus = "idle" | "active" | "on_break";

/** GET /work-sessions/break-types item shape (Phase 5). */
export interface BreakType {
  id: string;
  name: string;
  is_paid: boolean;
  max_minutes: number | null;
}

export interface HardwareInfo {
  hostname: string;
  os_type: DeviceOsType;
  os_name: string | null;
  os_version: string | null;
  cpu_model: string | null;
  cpu_cores: number | null;
  ram_total_gb: number | null;
  mac_address: string | null;
  agent_version: string | null;
}

/** Result of main/screenshotCapture.ts's captureScreenshot() — lives here
 * (not in main/) for the same cross-process-import reason as
 * TrayIconStatus above: preload needs the type without importing from
 * main/. */
export interface CapturedScreenshot {
  /** Base64-encoded PNG — IPC can't pass a raw Buffer as cleanly as a
   * string across the context-isolation bridge, and this is small enough
   * (one image, on-demand only — see backend's DeviceScreenshot docstring)
   * that base64's ~33% overhead doesn't matter. */
  base64Png: string;
  width: number;
  height: number;
}

/** One entry from the backend heartbeat response's `actions` array (see
 * POST /devices/heartbeat's docstring — "metrics in, pending actions
 * out"). Only `action` is guaranteed; the rest are per-action-type
 * fields the backend attaches when queuing (see devices.py's
 * _queue_device_action call sites). */
export interface PendingDeviceAction {
  action: "lock" | "restart" | "shutdown" | "message" | "screenshot" | string;
  requested_by?: string;
  text?: string;
}

/** One matched entry from main/activityTracker.ts's drainPendingAlerts()
 * — mirrors the backend's AlertUploadItem shape exactly (see
 * POST /devices/alerts/upload) so deviceService.uploadAlerts() can pass
 * these straight through with no reshaping. */
export interface WatchlistAlert {
  alert_type: "flagged_app_usage" | "flagged_browsing";
  matched_term: string;
  detail: string;
  occurred_at: string;
}

/** POST /devices/heartbeat response shape — see backend's return
 * statement in devices.py's heartbeat(). */
export interface HeartbeatResponse {
  actions: PendingDeviceAction[];
  health_score: number | null;
  activity_watchlist: string[];
}

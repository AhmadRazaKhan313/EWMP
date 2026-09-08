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

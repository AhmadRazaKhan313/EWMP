import os from "os";
import { app } from "electron";
import type { DeviceOsType, HardwareInfo } from "@shared/deviceTypes";

/**
 * Renderer-side equivalent of agent/ewmp_agent.py's
 * collect_static_hardware_info() — gathered once at enrollment, not on
 * every heartbeat. Must run in the main process: os.networkInterfaces()
 * and os.cpus() aren't available with nodeIntegration: false in the
 * renderer (see main/index.ts webPreferences), so this is exposed to the
 * renderer only via the narrow IPC bridge in preload/index.ts.
 *
 * Disk usage is deliberately NOT collected here — Node's `os` module has
 * no built-in cross-platform disk API (the Python agent uses
 * psutil.disk_usage for this). That lands in the item #3 "System
 * metrics" DoD cycle instead, alongside live CPU/RAM % on every
 * heartbeat, rather than adding a new native dependency just for one
 * static field here. `disk_total_gb` is optional on the backend's
 * SelfEnrollRequest for exactly this reason.
 */
export function detectOsType(): DeviceOsType {
  switch (process.platform) {
    case "win32":
      return "windows";
    case "linux":
      return "linux";
    case "darwin":
      return "macos";
    default:
      return "other";
  }
}

/** First non-internal interface with a real (non-zero) MAC address —
 * same "good enough for device identity" approach as the Python agent's
 * uuid.getnode() fallback, not a claim that every interface is stable. */
export function firstMacAddress(interfaces: NodeJS.Dict<os.NetworkInterfaceInfo[]>): string | null {
  for (const entries of Object.values(interfaces)) {
    for (const entry of entries ?? []) {
      if (!entry.internal && entry.mac && entry.mac !== "00:00:00:00:00:00") {
        return entry.mac;
      }
    }
  }
  return null;
}

export function getHardwareInfo(): HardwareInfo {
  const cpus = os.cpus();
  return {
    hostname: os.hostname(),
    os_type: detectOsType(),
    os_name: process.platform,
    os_version: os.release(),
    cpu_model: cpus[0]?.model ?? null,
    cpu_cores: cpus.length || null,
    ram_total_gb: Math.round((os.totalmem() / 1024 ** 3) * 10) / 10,
    mac_address: firstMacAddress(os.networkInterfaces()),
    agent_version: app.getVersion(),
  };
}

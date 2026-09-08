import { useEffect } from "react";
import { deviceService } from "../services/deviceService";
import type { DeviceStatus } from "../store/deviceStore";

/** Matches backend's `settings.DEVICE_HEARTBEAT_INTERVAL_SECONDS` default
 * (see backend/app/core/config.py). Backend only flips a stale device to
 * OFFLINE after `DEVICE_OFFLINE_AFTER_SECONDS` (180s, i.e. ~3 missed
 * beats) of silence, so an occasional dropped tick here doesn't flap the
 * admin dashboard's status. */
const HEARTBEAT_INTERVAL_MS = 60_000;

/**
 * Keeps the admin-side Devices table's online/offline status accurate for
 * as long as the desktop app is running.
 *
 * Enrollment (POST /devices/self-enroll) only ever runs once and sets the
 * device ONLINE at that moment — nothing about a one-time login call could
 * possibly reflect whether the machine is still online an hour, or a day,
 * later. This hook is what keeps that status live: it fires one heartbeat
 * immediately on mount (so the table updates right away rather than
 * waiting a full interval) and then again every HEARTBEAT_INTERVAL_MS
 * for as long as `deviceStatus === "enrolled"`.
 *
 * Deliberately does nothing for any other DeviceStatus — "needs_consent"/
 * "needs_finish"/"enrolling" all mean there's no agent token yet for
 * deviceService.sendHeartbeat() to use, and it would just no-op anyway
 * (see its own guard), so skipping the interval entirely there avoids
 * pointless wake-ups.
 */
export function useDeviceHeartbeat(deviceStatus: DeviceStatus): void {
  useEffect(() => {
    if (deviceStatus !== "enrolled") return;

    void deviceService.sendHeartbeat();
    const timer = setInterval(() => {
      void deviceService.sendHeartbeat();
    }, HEARTBEAT_INTERVAL_MS);

    return (): void => clearInterval(timer);
  }, [deviceStatus]);
}

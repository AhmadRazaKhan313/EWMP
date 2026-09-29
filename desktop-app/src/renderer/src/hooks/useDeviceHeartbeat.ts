import { useEffect } from "react";
import { deviceService } from "../services/deviceService";
import { useDeviceStore, type DeviceStatus } from "../store/deviceStore";
import type { PendingDeviceAction } from "@shared/deviceTypes";

/** Matches backend's `settings.DEVICE_HEARTBEAT_INTERVAL_SECONDS` default
 * (see backend/app/core/config.py). Backend only flips a stale device to
 * OFFLINE after `DEVICE_OFFLINE_AFTER_SECONDS` (180s, i.e. ~3 missed
 * beats) of silence, so an occasional dropped tick here doesn't flap the
 * admin dashboard's status. */
const HEARTBEAT_INTERVAL_MS = 60_000;

/**
 * Fulfils a queued "screenshot" action (see backend's
 * POST /devices/{id}/screenshot/request — "ONE screenshot... no
 * continuous recording"): captures the primary display in the main
 * process and uploads it. Failures are logged, not thrown — a screenshot
 * that fails to capture/upload should never crash the heartbeat loop
 * that everything else (online status) depends on; the admin can just
 * request another one.
 */
async function fulfilScreenshotAction(action: PendingDeviceAction): Promise<void> {
  try {
    const { base64Png, width, height } = await window.ewmp.device.captureScreenshot();
    await deviceService.uploadScreenshot(base64Png, { width, height, requestedBy: action.requested_by });
  } catch (err) {
    console.error("[monitoring] screenshot capture/upload failed:", err);
  }
}

/**
 * Processes the `actions` array handed back on every heartbeat. Only
 * "screenshot" is implemented so far — lock/restart/shutdown/message are
 * queued correctly by the backend already (see devices.py's
 * _queue_device_action call sites) but have no agent-side handler yet;
 * logging them (rather than silently dropping) keeps that gap visible
 * instead of it looking like the feature works end-to-end when it
 * doesn't.
 */
function processPendingActions(actions: PendingDeviceAction[]): void {
  for (const action of actions) {
    if (action.action === "screenshot") {
      void fulfilScreenshotAction(action);
    } else {
      console.warn(`[monitoring] received a "${action.action}" action — not yet implemented on desktop, ignoring.`);
    }
  }
}

/**
 * Keeps the admin-side Devices table's online/offline status accurate for
 * as long as the desktop app is running, and now also drains the
 * heartbeat's queued actions (currently: on-demand screenshots — see
 * processPendingActions above).
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

    async function beat(): Promise<void> {
      try {
        const response = await deviceService.sendHeartbeat();
        if (response?.actions?.length) {
          processPendingActions(response.actions);
        }
        // Keep the main process's activity tracker's watchlist current —
        // the org can change this list from the admin side at any time,
        // and the next heartbeat (max HEARTBEAT_INTERVAL_MS later) is
        // when a running device picks up the change, same lag as every
        // other heartbeat-delivered setting in this app.
        if (response) {
          void window.ewmp.activity.setWatchlist(response.activity_watchlist ?? []);
        }
        // Drain and upload whatever flagged-window matches accumulated
        // in the main process since the last beat — see
        // activityTracker.ts's dedup note for why this is a small list,
        // not one entry per poll tick.
        const alerts = await window.ewmp.activity.drainAlerts();
        if (alerts.length > 0) {
          await deviceService.uploadAlerts(alerts);
        }
      } catch (err) {
        // 401 from /devices/heartbeat means the backend's get_current_device
        // rejected this device — either its token is bad, or (just as
        // likely in practice — see a DB reset/restore, or the device being
        // decommissioned from the admin side) the Device row itself is
        // simply gone even though this install still has a cached
        // deviceId/agentToken from before. Either way the local "enrolled"
        // status is now a lie; self-heal by clearing it and falling back
        // to "needs_finish" so the next retry re-enrolls from scratch and
        // the device reappears in the admin fleet table.
        //
        // Anything else (network blip, server briefly down, timeout) is
        // transient — NOT treated as invalidation, since that would force
        // a full re-enroll on every dropped wifi connection. Just skip
        // this tick; the next interval retries on its own.
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 401) {
          void useDeviceStore.getState().handleDeviceInvalidated();
        }
      }
    }

    void beat();
    const timer = setInterval(() => void beat(), HEARTBEAT_INTERVAL_MS);

    return (): void => clearInterval(timer);
  }, [deviceStatus]);
}

import { create } from "zustand";
import { deviceService } from "../services/deviceService";

/**
 * Phase 4 item #1 — self-enrollment.
 *
 * "checking"      — reading local state, hasn't decided anything yet.
 *                    Non-blocking by design: App.tsx treats this the
 *                    same as "needs_consent" only for a brief instant
 *                    while local secureStore reads resolve, never as a
 *                    long-lived spinner.
 * "needs_consent" — employee has never clicked through ConsentNotice on
 *                    this install. The ONLY status that gates the app.
 * "enrolled"      — a device_id/agent_token already exist locally.
 *                    init() does NOT re-call the API just to confirm
 *                    this — POST /devices/self-enroll only runs from an
 *                    explicit consent/retry action, never silently on
 *                    every launch.
 * "needs_finish"  — consent was given (so never re-show the notice) but
 *                    the enroll call hasn't succeeded yet (first attempt
 *                    failed, or the app quit in between). Non-blocking:
 *                    AuthenticatedPlaceholder can surface a small
 *                    "Finish device setup" retry affordance, but the
 *                    employee can keep using Check In/Out regardless —
 *                    fleet enrollment failing must never block payroll-
 *                    relevant attendance actions.
 * "enrolling"     — a self-enroll call is in flight (consent click or
 *                    retry).
 */
export type DeviceStatus = "checking" | "needs_consent" | "needs_finish" | "enrolling" | "enrolled";

interface DeviceState {
  status: DeviceStatus;
  error: string | null;
  init: () => Promise<void>;
  acknowledgeAndEnroll: () => Promise<void>;
  retryEnrollment: () => Promise<void>;
  handleDeviceInvalidated: () => Promise<void>;
}

export const useDeviceStore = create<DeviceState>((set) => ({
  status: "checking",
  error: null,

  init: async (): Promise<void> => {
    try {
      const [consent, deviceId] = await Promise.all([
        window.ewmp.secureStore.get("deviceConsentAcknowledged"),
        window.ewmp.secureStore.get("deviceId"),
      ]);
      if (!consent) {
        set({ status: "needs_consent" });
      } else if (deviceId) {
        set({ status: "enrolled" });
      } else {
        set({ status: "needs_finish" });
      }
    } catch {
      // Can't read local device state at all (bridge unavailable, disk
      // error, etc.) — fail OPEN. Enrollment is a fleet-management nicety,
      // not a security gate; it must never be able to lock an employee
      // out of clocking in because of an unrelated local-storage hiccup.
      set({ status: "enrolled" });
    }
  },

  acknowledgeAndEnroll: async (): Promise<void> => {
    await window.ewmp.secureStore.set("deviceConsentAcknowledged", "true");
    await performEnrollment(set);
  },

  retryEnrollment: async (): Promise<void> => {
    await performEnrollment(set);
  },

  /**
   * Self-heal for a stale local device: init() only checks whether a
   * deviceId exists LOCALLY, never whether the backend still recognizes
   * it — cheap and non-blocking, per this file's own design notes above.
   * That's fine day-to-day, but breaks down the moment the backend's
   * Device row is gone while the local cache still has an old
   * deviceId/agentToken (e.g. a database reset/restore, or the device
   * being decommissioned from the admin side) — the app would sit
   * forever believing it's "enrolled" while every heartbeat silently
   * 401s and the device never appears in the fleet table again.
   *
   * useDeviceHeartbeat.ts calls this specifically when a heartbeat comes
   * back 401 ("Device not enrolled" — see backend's get_current_device,
   * which returns exactly this for BOTH a truly-invalid token and a
   * device row that no longer exists, so 401 is an unambiguous signal
   * either way). Clearing the cached IDs flips status back to
   * "needs_finish", which surfaces the existing "Finish device setup"
   * retry affordance — the very next click re-runs self-enroll and the
   * device reappears on the admin side with a fresh row.
   */
  handleDeviceInvalidated: async (): Promise<void> => {
    await Promise.all([
      window.ewmp.secureStore.delete("deviceId"),
      window.ewmp.secureStore.delete("agentToken"),
    ]);
    set({ status: "needs_finish", error: "Device session expired — click to re-register this device." });
  },
}));

async function performEnrollment(set: (partial: Partial<DeviceState>) => void): Promise<void> {
  set({ status: "enrolling", error: null });
  try {
    const hardware = await deviceService.getHardwareInfo();
    const { device_id, agent_token } = await deviceService.selfEnroll(hardware);
    await window.ewmp.secureStore.set("deviceId", device_id);
    await window.ewmp.secureStore.set("agentToken", agent_token);
    set({ status: "enrolled", error: null });
  } catch (err) {
    // Consent itself is never re-asked for over a failed enrollment call
    // (see acknowledgeAndEnroll, which persists the flag before this
    // runs) — only status/error reflect the failure here.
    set({ status: "needs_finish", error: extractErrorMessage(err) });
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractErrorMessage(err: any): string {
  return err?.response?.data?.detail || err?.response?.data?.message || err?.message || "Device setup failed";
}

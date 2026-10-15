import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useDeviceHeartbeat } from "../useDeviceHeartbeat";
import { deviceService } from "../../services/deviceService";
import { useDeviceStore } from "../../store/deviceStore";
import type { HeartbeatResponse } from "@shared/deviceTypes";

function response(overrides: Partial<HeartbeatResponse> = {}): HeartbeatResponse {
  return { actions: [], health_score: 100, activity_watchlist: [], ...overrides };
}

describe("useDeviceHeartbeat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each(["checking", "needs_consent", "needs_finish", "enrolling"] as const)(
    "does nothing for deviceStatus=%s",
    (status) => {
      const spy = vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(null);
      renderHook(() => useDeviceHeartbeat(status));
      expect(spy).not.toHaveBeenCalled();
    },
  );

  it("fires one heartbeat immediately on mount once enrolled", () => {
    const spy = vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(null);
    renderHook(() => useDeviceHeartbeat("enrolled"));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("fires again every 60 seconds while enrolled", () => {
    const spy = vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(null);
    renderHook(() => useDeviceHeartbeat("enrolled"));
    spy.mockClear(); // ignore the mount-time beat

    vi.advanceTimersByTime(60_000);
    expect(spy).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(60_000);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("stops polling once the interval is torn down (unmount)", () => {
    const spy = vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(null);
    const { unmount } = renderHook(() => useDeviceHeartbeat("enrolled"));
    spy.mockClear();

    unmount();
    vi.advanceTimersByTime(180_000);

    expect(spy).not.toHaveBeenCalled();
  });

  it("stops polling if deviceStatus moves away from enrolled (e.g. a later logout)", () => {
    const spy = vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(null);
    const { rerender } = renderHook(({ status }) => useDeviceHeartbeat(status), {
      initialProps: { status: "enrolled" as const },
    });
    spy.mockClear();

    rerender({ status: "needs_consent" as never });
    vi.advanceTimersByTime(180_000);

    expect(spy).not.toHaveBeenCalled();
  });

  describe("pending action handling (monitoring feature)", () => {
    it("captures and uploads a screenshot when a 'screenshot' action is queued", async () => {
      vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(
        response({ actions: [{ action: "screenshot", requested_by: "admin-1" }] }),
      );
      window.ewmp.device.captureScreenshot = vi.fn().mockResolvedValue({
        base64Png: "AAAA", width: 1920, height: 1080,
      });
      const uploadSpy = vi.spyOn(deviceService, "uploadScreenshot").mockResolvedValue(undefined);

      renderHook(() => useDeviceHeartbeat("enrolled"));
      await vi.waitFor(() => expect(uploadSpy).toHaveBeenCalledTimes(1));

      expect(uploadSpy).toHaveBeenCalledWith("AAAA", { width: 1920, height: 1080, requestedBy: "admin-1" });
    });

    it("does not crash the heartbeat loop if screenshot capture fails", async () => {
      vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(
        response({ actions: [{ action: "screenshot" }] }),
      );
      window.ewmp.device.captureScreenshot = vi.fn().mockRejectedValue(new Error("capture failed"));
      const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

      renderHook(() => useDeviceHeartbeat("enrolled"));
      await vi.waitFor(() => expect(errSpy).toHaveBeenCalled());

      errSpy.mockRestore();
    });

    it("logs (but doesn't throw) for an unimplemented action type like lock/restart", async () => {
      vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(
        response({ actions: [{ action: "lock", requested_by: "admin-1" }] }),
      );
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      renderHook(() => useDeviceHeartbeat("enrolled"));
      await vi.waitFor(() => expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("lock")));

      warnSpy.mockRestore();
    });

    it("processes multiple queued actions from a single heartbeat", async () => {
      vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(
        response({ actions: [{ action: "screenshot" }, { action: "message", text: "hi" }] }),
      );
      window.ewmp.device.captureScreenshot = vi.fn().mockResolvedValue({ base64Png: "x", width: 1, height: 1 });
      const uploadSpy = vi.spyOn(deviceService, "uploadScreenshot").mockResolvedValue(undefined);
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      renderHook(() => useDeviceHeartbeat("enrolled"));
      await vi.waitFor(() => expect(uploadSpy).toHaveBeenCalledTimes(1));
      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("message"));

      warnSpy.mockRestore();
    });
  });

  describe("self-heal on a stale local device (401 from heartbeat)", () => {
    it("clears the cached device and falls back to needs_finish on a 401", async () => {
      vi.spyOn(deviceService, "sendHeartbeat").mockRejectedValue({ response: { status: 401 } });
      const healSpy = vi.spyOn(useDeviceStore.getState(), "handleDeviceInvalidated").mockResolvedValue(undefined);

      renderHook(() => useDeviceHeartbeat("enrolled"));
      await vi.waitFor(() => expect(healSpy).toHaveBeenCalledTimes(1));
    });

    it("does NOT self-heal on a transient network error (only a real 401 counts)", async () => {
      vi.spyOn(deviceService, "sendHeartbeat").mockRejectedValue(new Error("Network Error"));
      const healSpy = vi.spyOn(useDeviceStore.getState(), "handleDeviceInvalidated").mockResolvedValue(undefined);

      renderHook(() => useDeviceHeartbeat("enrolled"));
      // Give the rejected promise a tick to settle, then confirm it was
      // never treated as invalidation — a dropped wifi connection must
      // not force a full re-enroll.
      await vi.waitFor(() => expect(deviceService.sendHeartbeat).toHaveBeenCalled());
      expect(healSpy).not.toHaveBeenCalled();
    });

    it("does NOT self-heal on a 500 (server error is not the device's fault)", async () => {
      vi.spyOn(deviceService, "sendHeartbeat").mockRejectedValue({ response: { status: 500 } });
      const healSpy = vi.spyOn(useDeviceStore.getState(), "handleDeviceInvalidated").mockResolvedValue(undefined);

      renderHook(() => useDeviceHeartbeat("enrolled"));
      await vi.waitFor(() => expect(deviceService.sendHeartbeat).toHaveBeenCalled());
      expect(healSpy).not.toHaveBeenCalled();
    });
  });

  describe("activity watchlist + alert upload (social-media alert feature)", () => {
    it("pushes the heartbeat's activity_watchlist into the main-process tracker", async () => {
      vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(
        response({ activity_watchlist: ["facebook.com", "instagram.com"] }),
      );
      window.ewmp.activity.setWatchlist = vi.fn().mockResolvedValue(undefined);
      window.ewmp.activity.drainAlerts = vi.fn().mockResolvedValue([]);

      renderHook(() => useDeviceHeartbeat("enrolled"));

      await vi.waitFor(() =>
        expect(window.ewmp.activity.setWatchlist).toHaveBeenCalledWith(["facebook.com", "instagram.com"]),
      );
    });

    it("drains and uploads any alerts the tracker accumulated since the last beat", async () => {
      vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(response());
      window.ewmp.activity.setWatchlist = vi.fn().mockResolvedValue(undefined);
      window.ewmp.activity.drainAlerts = vi.fn().mockResolvedValue([
        { alert_type: "flagged_browsing", matched_term: "facebook.com", detail: "…", occurred_at: "2026-01-01T00:00:00Z" },
      ]);
      const uploadSpy = vi.spyOn(deviceService, "uploadAlerts").mockResolvedValue({ created: 1, suppressed_by_allowlist: 0 });

      renderHook(() => useDeviceHeartbeat("enrolled"));

      await vi.waitFor(() => expect(uploadSpy).toHaveBeenCalledTimes(1));
      expect(uploadSpy.mock.calls[0]?.[0]).toHaveLength(1);
    });

    it("does not call uploadAlerts when there is nothing to drain", async () => {
      vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(response());
      window.ewmp.activity.setWatchlist = vi.fn().mockResolvedValue(undefined);
      window.ewmp.activity.drainAlerts = vi.fn().mockResolvedValue([]);
      const uploadSpy = vi.spyOn(deviceService, "uploadAlerts").mockResolvedValue(null);

      renderHook(() => useDeviceHeartbeat("enrolled"));

      await vi.waitFor(() => expect(window.ewmp.activity.drainAlerts).toHaveBeenCalled());
      expect(uploadSpy).not.toHaveBeenCalled();
    });
  });
});

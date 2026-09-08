import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useDeviceHeartbeat } from "../useDeviceHeartbeat";
import { deviceService } from "../../services/deviceService";

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
      const spy = vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(undefined);
      renderHook(() => useDeviceHeartbeat(status));
      expect(spy).not.toHaveBeenCalled();
    },
  );

  it("fires one heartbeat immediately on mount once enrolled", () => {
    const spy = vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(undefined);
    renderHook(() => useDeviceHeartbeat("enrolled"));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("fires again every 60 seconds while enrolled", () => {
    const spy = vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(undefined);
    renderHook(() => useDeviceHeartbeat("enrolled"));
    spy.mockClear(); // ignore the mount-time beat

    vi.advanceTimersByTime(60_000);
    expect(spy).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(60_000);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("stops polling once the interval is torn down (unmount)", () => {
    const spy = vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(undefined);
    const { unmount } = renderHook(() => useDeviceHeartbeat("enrolled"));
    spy.mockClear();

    unmount();
    vi.advanceTimersByTime(180_000);

    expect(spy).not.toHaveBeenCalled();
  });

  it("stops polling if deviceStatus moves away from enrolled (e.g. a later logout)", () => {
    const spy = vi.spyOn(deviceService, "sendHeartbeat").mockResolvedValue(undefined);
    const { rerender } = renderHook(({ status }) => useDeviceHeartbeat(status), {
      initialProps: { status: "enrolled" as const },
    });
    spy.mockClear();

    rerender({ status: "needs_consent" as never });
    vi.advanceTimersByTime(180_000);

    expect(spy).not.toHaveBeenCalled();
  });
});

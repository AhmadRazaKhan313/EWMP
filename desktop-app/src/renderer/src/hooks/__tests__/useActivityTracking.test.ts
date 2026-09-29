import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useActivityTracking } from "../useActivityTracking";

describe("useActivityTracking", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.ewmp.activity.start = vi.fn().mockResolvedValue(undefined);
    window.ewmp.activity.stop = vi.fn().mockResolvedValue(undefined);
  });

  it.each(["active", "on_break"] as const)("starts tracking when timer status is %s", (status) => {
    renderHook(() => useActivityTracking(status));
    expect(window.ewmp.activity.start).toHaveBeenCalled();
    expect(window.ewmp.activity.stop).not.toHaveBeenCalled();
  });

  it.each(["loading", "idle", "ended"] as const)("stops tracking (or never starts it) when timer status is %s", (status) => {
    renderHook(() => useActivityTracking(status));
    expect(window.ewmp.activity.stop).toHaveBeenCalled();
    expect(window.ewmp.activity.start).not.toHaveBeenCalled();
  });

  it("stops tracking when transitioning from active to idle (e.g. check-out)", () => {
    const { rerender } = renderHook(({ status }) => useActivityTracking(status), {
      initialProps: { status: "active" as const },
    });
    expect(window.ewmp.activity.start).toHaveBeenCalledTimes(1);

    rerender({ status: "idle" as never });
    expect(window.ewmp.activity.stop).toHaveBeenCalled();
  });

  it("stops tracking on unmount even if still checked in", () => {
    const { unmount } = renderHook(() => useActivityTracking("active"));
    vi.mocked(window.ewmp.activity.stop).mockClear();

    unmount();

    expect(window.ewmp.activity.stop).toHaveBeenCalled();
  });
});

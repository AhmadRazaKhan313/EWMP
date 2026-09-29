import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTraySync } from "../useTraySync";
import { useTimerStore } from "../../store/timerStore";

describe("useTraySync", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTimerStore.setState({ status: "loading", sessionId: null, startedAt: null, elapsedSeconds: 0, error: null });
  });

  it("reports idle for the initial loading state", () => {
    const spy = vi.spyOn(window.ewmp.tray, "setStatus");
    renderHook(() => useTraySync());
    expect(spy).toHaveBeenCalledWith("idle");
  });

  it("re-reports the tray status whenever timerStore.status changes", () => {
    const spy = vi.spyOn(window.ewmp.tray, "setStatus");
    renderHook(() => useTraySync());
    spy.mockClear();

    act(() => useTimerStore.setState({ status: "active" }));
    expect(spy).toHaveBeenCalledWith("active");

    act(() => useTimerStore.setState({ status: "on_break" }));
    expect(spy).toHaveBeenCalledWith("on_break");

    act(() => useTimerStore.setState({ status: "idle" }));
    expect(spy).toHaveBeenCalledWith("idle");
  });

  it("does not call the tray bridge again for unrelated store field changes", () => {
    const spy = vi.spyOn(window.ewmp.tray, "setStatus");
    renderHook(() => useTraySync());
    spy.mockClear();

    act(() => useTimerStore.setState({ elapsedSeconds: 42 })); // status unchanged (still "loading" -> idle)
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("useTraySync tooltip (mini-timer)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTimerStore.setState({ status: "loading", sessionId: null, startedAt: null, elapsedSeconds: 0, error: null });
  });

  it("does not touch the tooltip while idle", () => {
    const spy = vi.spyOn(window.ewmp.tray, "setTooltip");
    renderHook(() => useTraySync());
    act(() => useTimerStore.setState({ elapsedSeconds: 30 }));
    expect(spy).not.toHaveBeenCalled();
  });

  it("shows a live elapsed time once active", () => {
    const spy = vi.spyOn(window.ewmp.tray, "setTooltip");
    useTimerStore.setState({ status: "active", elapsedSeconds: 65 });
    renderHook(() => useTraySync());
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("01:05"));
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("Checked in — working"));
  });

  it("updates the tooltip on every elapsedSeconds tick without rebuilding the full status/menu", () => {
    const tooltipSpy = vi.spyOn(window.ewmp.tray, "setTooltip");
    const statusSpy = vi.spyOn(window.ewmp.tray, "setStatus");
    useTimerStore.setState({ status: "active", elapsedSeconds: 10 });
    renderHook(() => useTraySync());
    tooltipSpy.mockClear();
    statusSpy.mockClear();

    act(() => useTimerStore.setState({ elapsedSeconds: 11 }));

    expect(tooltipSpy).toHaveBeenCalledWith(expect.stringContaining("00:11"));
    expect(statusSpy).not.toHaveBeenCalled(); // status field itself didn't change
  });

  it("reflects the on_break label while on break", () => {
    const spy = vi.spyOn(window.ewmp.tray, "setTooltip");
    useTimerStore.setState({ status: "on_break", elapsedSeconds: 5 });
    renderHook(() => useTraySync());
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("On break"));
  });
});

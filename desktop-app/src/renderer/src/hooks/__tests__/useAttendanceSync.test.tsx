/**
 * useAttendanceSync -- how a window learns the attendance state changed.
 */
import { StrictMode } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAttendanceSync, ATTENDANCE_SYNC_INTERVAL_MS } from "../useAttendanceSync";

let nudge: (() => void) | null = null;
const unsubscribe = vi.fn();
const onChanged = vi.fn((cb: () => void) => { nudge = cb; return unsubscribe; });

describe("useAttendanceSync", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    nudge = null;
    (window as unknown as { ewmp: unknown }).ewmp = { attendance: { onChanged, notifyChanged: vi.fn() } };
  });
  afterEach(() => vi.useRealTimers());

  it("re-reads the server on a steady interval (a change from the website / another device)", async () => {
    const sync = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAttendanceSync(sync));
    expect(sync).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(ATTENDANCE_SYNC_INTERVAL_MS * 3); });
    expect(sync).toHaveBeenCalledTimes(3);
  });

  it("re-reads IMMEDIATELY when another window of the app changes the state", async () => {
    const sync = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAttendanceSync(sync));
    await act(async () => { nudge?.(); });
    expect(sync).toHaveBeenCalledTimes(1);                     // no waiting for the interval
  });

  it("re-reads when the window is focused and when the network comes back", async () => {
    const sync = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAttendanceSync(sync));
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    await act(async () => { window.dispatchEvent(new Event("online")); });
    expect(sync).toHaveBeenCalledTimes(2);
  });

  it("never runs two reads at once (a slow server can't pile requests up)", async () => {
    let finish!: () => void;
    const sync = vi.fn(() => new Promise<void>((r) => { finish = r; }));
    renderHook(() => useAttendanceSync(sync));
    await act(async () => { await vi.advanceTimersByTimeAsync(ATTENDANCE_SYNC_INTERVAL_MS * 3); });
    expect(sync).toHaveBeenCalledTimes(1);                     // the first is still running
    await act(async () => { finish(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(ATTENDANCE_SYNC_INTERVAL_MS); });
    expect(sync).toHaveBeenCalledTimes(2);
  });

  it("does nothing when disabled (nobody signed in)", async () => {
    const sync = vi.fn();
    renderHook(() => useAttendanceSync(sync, { enabled: false }));
    await act(async () => { await vi.advanceTimersByTimeAsync(ATTENDANCE_SYNC_INTERVAL_MS * 2); window.dispatchEvent(new Event("focus")); });
    expect(sync).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("cleans up completely on unmount: timer, DOM listeners and the IPC subscription", async () => {
    const sync = vi.fn().mockResolvedValue(undefined);
    const { unmount } = renderHook(() => useAttendanceSync(sync));
    unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(ATTENDANCE_SYNC_INTERVAL_MS * 3); window.dispatchEvent(new Event("focus")); });
    expect(sync).not.toHaveBeenCalled();
  });

  it("re-rendering with a new sync function does not re-subscribe, and the newest one is used", async () => {
    const first = vi.fn().mockResolvedValue(undefined), second = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderHook(({ fn }) => useAttendanceSync(fn), { initialProps: { fn: first } });
    rerender({ fn: second }); rerender({ fn: second });
    expect(onChanged).toHaveBeenCalledTimes(1);
    await act(async () => { nudge?.(); });
    expect(second).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
  });

  it("StrictMode's double mount leaves exactly one live subscription", () => {
    const sync = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAttendanceSync(sync), { wrapper: StrictMode });
    expect(onChanged.mock.calls.length - unsubscribe.mock.calls.length).toBe(1);
  });

  it("works without the Electron bridge", async () => {
    (window as unknown as { ewmp: unknown }).ewmp = undefined;
    const sync = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAttendanceSync(sync));
    await act(async () => { await vi.advanceTimersByTimeAsync(ATTENDANCE_SYNC_INTERVAL_MS); });
    expect(sync).toHaveBeenCalledTimes(1);
  });
});

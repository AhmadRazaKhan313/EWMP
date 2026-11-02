import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("../../services/breakLockService", () => ({
  breakLockService: { getMine: vi.fn(), requestUnlock: vi.fn() },
}));
import { breakLockService } from "../../services/breakLockService";
import { useBreakLock } from "../useBreakLock";
import { useTimerStore } from "../../store/timerStore";

const svc = breakLockService as unknown as { getMine: ReturnType<typeof vi.fn>; requestUnlock: ReturnType<typeof vi.fn> };

function info(over = {}) {
  const now = Date.now();
  return {
    server_time: new Date(now).toISOString(), has_break: true, phase: "active", locked: true,
    start: new Date(now - 60_000).toISOString(), end: new Date(now + 3_540_000).toISOString(),
    duration_minutes: 60, request: null, ...over,
  };
}
function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useBreakLock", () => {
  const setLocked = vi.fn().mockResolvedValue(undefined);
  const startBreak = vi.fn().mockResolvedValue(undefined);
  const endBreak = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.clearAllMocks();
    (window as unknown as { ewmp: object }).ewmp = { ...(window.ewmp ?? {}), breakLock: { setLocked } };
    useTimerStore.setState({ status: "active", startBreak, endBreak } as never);
  });
  afterEach(() => useTimerStore.setState({ status: "idle" } as never));

  it("locks the screen and pauses work time during the break", async () => {
    svc.getMine.mockResolvedValue(info());
    const { result } = renderHook(() => useBreakLock(true), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.locked).toBe(true));
    expect(setLocked).toHaveBeenCalledWith(true);
    expect(startBreak).toHaveBeenCalledTimes(1);
  });

  it("does nothing while signed out", async () => {
    svc.getMine.mockResolvedValue(info());
    const { result } = renderHook(() => useBreakLock(false), { wrapper: wrapper() });
    expect(result.current.locked).toBe(false);
    expect(svc.getMine).not.toHaveBeenCalled();
  });

  it("an approved unlock uncovers the screen and resumes work time", async () => {
    svc.getMine.mockResolvedValueOnce(info());
    const { result } = renderHook(() => useBreakLock(true), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.locked).toBe(true));
    useTimerStore.setState({ status: "on_break" } as never);

    svc.getMine.mockResolvedValue(info({ unlocked_by_admin: true, request: { id: "r", status: "approved", reason: null } }));
    svc.requestUnlock.mockResolvedValue(undefined);
    await act(async () => { await result.current.requestUnlock("deadline"); });
    await waitFor(() => expect(result.current.locked).toBe(false));
    expect(setLocked).toHaveBeenLastCalledWith(false);
    expect(endBreak).toHaveBeenCalledTimes(1);
    expect(svc.requestUnlock.mock.calls[0]?.[0]).toBe("deadline");
  });

  it("stays locked from the last known window when the server can't be reached", async () => {
    svc.getMine.mockResolvedValueOnce(info());
    const { result } = renderHook(() => useBreakLock(true), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.locked).toBe(true));
    svc.getMine.mockRejectedValue(new Error("offline"));
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    expect(result.current.locked).toBe(true);
  });

  it("does not end a pause the employee started themselves", async () => {
    useTimerStore.setState({ status: "on_break" } as never); // already on a manual break when the lock starts
    svc.getMine.mockResolvedValueOnce(info());
    const { result, rerender } = renderHook(() => useBreakLock(true), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.locked).toBe(true));
    expect(startBreak).not.toHaveBeenCalled();
    svc.getMine.mockResolvedValue(info({ unlocked_by_admin: true, request: { id: "r", status: "approved", reason: null } }));
    await act(async () => { await result.current.requestUnlock(""); });
    rerender();
    await waitFor(() => expect(result.current.locked).toBe(false));
    expect(endBreak).not.toHaveBeenCalled();
  });
});

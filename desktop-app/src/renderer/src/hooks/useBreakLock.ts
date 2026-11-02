import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { breakLockService } from "../services/breakLockService";
import { deriveBreakView, type BreakView } from "../lib/breakPhase";
import { useTimerStore } from "../store/timerStore";

const POLL_MS = 15_000;

export interface BreakLockState extends BreakView {
  requestStatus: "pending" | "approved" | "denied" | null;
  requestUnlock: (reason: string) => Promise<void>;
  requesting: boolean;
  error: string | null;
}

/**
 * Break-time lock: polls the server for today's break window, locks the screen
 * while it runs, pauses work time while locked and resumes it once the break is
 * over or the admin approved an unlock.
 */
export function useBreakLock(enabled: boolean): BreakLockState {
  const { data, refetch, dataUpdatedAt } = useQuery({
    queryKey: ["break", "me"],
    queryFn: breakLockService.getMine,
    enabled,
    refetchInterval: POLL_MS,
    retry: false, // keeps the last good answer on failure: offline = last-known window
  });

  // server clock minus this PC's clock, measured when the answer arrived
  const offsetMs = useMemo(
    () => (data ? Date.parse(data.server_time) - (dataUpdatedAt || Date.now()) : 0),
    [data, dataUpdatedAt],
  );

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return (): void => clearInterval(id);
  }, [enabled]);

  const view = deriveBreakView(enabled ? data : undefined, offsetMs, now);
  const locked = enabled && view.locked;

  // Cover / uncover the screen (main process).
  const lastSent = useRef(false);
  useEffect(() => {
    if (lastSent.current === locked) return;
    lastSent.current = locked;
    void window.ewmp?.breakLock?.setLocked(locked);
  }, [locked]);

  // Work time stops while locked and restarts afterwards. Only ever ends a pause WE started.
  const pausedByLock = useRef(false);
  useEffect(() => {
    const timer = useTimerStore.getState();
    if (locked && !pausedByLock.current && timer.status === "active") {
      pausedByLock.current = true;
      void timer.startBreak();
    } else if (!locked && pausedByLock.current) {
      pausedByLock.current = false;
      if (timer.status === "on_break") void timer.endBreak();
    }
  }, [locked]);

  // Native 5-minute warning, once per break.
  const warned = useRef<string | null>(null);
  useEffect(() => {
    if (view.phase !== "warning" || !data?.start || warned.current === data.start) return;
    warned.current = data.start;
    try {
      if (typeof Notification !== "undefined") {
        new Notification("Break starts soon", { body: "Your computer will lock for the break in 5 minutes. Save your work." });
      }
    } catch { /* notifications unavailable: the in-app banner still shows */ }
  }, [view.phase, data?.start]);

  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: breakLockService.requestUnlock,
    onSuccess: () => { setError(null); void refetch(); },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { message?: string } } })?.response?.data?.message;
      setError(msg ?? "Couldn't send the request. Check your connection and try again.");
    },
  });
  const requestUnlock = useCallback(async (reason: string) => { await mutation.mutateAsync(reason).catch(() => undefined); }, [mutation]);

  return { ...view, requestStatus: data?.request?.status ?? null, requestUnlock, requesting: mutation.isPending, error };
}

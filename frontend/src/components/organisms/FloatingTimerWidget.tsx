"use client";

/**
 * Floating check-in / break widget for the website: a glass card pinned to the
 * bottom-right of every dashboard page, with the work timer, today's break time
 * and the two buttons -- Check In/Check Out and Break On/Break Off. It can be
 * minimised to a small pill (remembered per browser).
 *
 * Same data as the desktop app's widget and the Attendance page's card: the
 * server's work session (GET /work-sessions/me/active) is the single source of
 * truth (lib/attendanceSession.ts), re-read every few seconds and whenever the
 * tab is focused or the network returns, so a check-in or break made in the
 * desktop app shows up here on its own -- and the other way round. It shares the
 * ["work-session","active"] query with CheckInWidget, so the two never disagree
 * on the same page, and its timers count from the SERVER's clock.
 *
 * Check In/Out go through /attendance/check-in|out (what CheckInWidget uses, so
 * lateness and overtime are recorded); the backend keeps the work session in
 * step. Break On/Off use the same /work-sessions/{id}/break/* endpoints as the
 * desktop app.
 */

import { apiErrorText } from "@/utils/api-error";
import { useEffect, useState } from "react";
import { ChevronUp, Minus } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { useAuthStore } from "@/store/auth.store";
import { CoffeeCupIcon, PersonClockIcon } from "@/components/atoms/FloatingWidgetIcons";
import {
  ACTIVE_SESSION_KEY,
  ATTENDANCE_QUERY_OPTIONS,
  fetchActiveSession,
  sessionClock,
} from "@/services/attendanceSession.service";
import "@/styles/floating-widget.css";

// The thin line under the timer fills as today's break time approaches this.
const BREAK_ALLOWANCE_SECONDS = 60 * 60;
export const COLLAPSED_KEY = "ewmp.floatingTimer.collapsed";

const pad = (n: number): string => String(n).padStart(2, "0");
function hms(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

function messageFrom(err: unknown, fallback: string): string {
  return apiErrorText(err, fallback);
}

export function FloatingTimerWidget(): JSX.Element | null {
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const [collapsed, setCollapsed] = useState<boolean | null>(null); // null until mounted (no SSR mismatch)
  const [now, setNow] = useState(() => Date.now());

  const enabled = !!user?.has_employee_profile && !user?.must_change_password;

  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem(COLLAPSED_KEY); } catch { /* storage blocked */ }
    // First visit: open on a wide screen, tucked away on a phone.
    setCollapsed(saved === null ? window.innerWidth < 640 : saved === "1");
  }, []);

  const { data: session, isLoading } = useQuery({
    queryKey: ACTIVE_SESSION_KEY,
    queryFn: fetchActiveSession,
    ...ATTENDANCE_QUERY_OPTIONS,
    enabled,
  });

  const { isCheckedIn, isOnBreak, workedSeconds: worked, breakSeconds: breakTotal } = sessionClock(session, now);

  useEffect(() => {
    if (!isCheckedIn) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isCheckedIn]);

  function refreshAll(): void {
    void qc.invalidateQueries({ queryKey: ["work-session"] });
    void qc.invalidateQueries({ queryKey: ["attendance"] });
    void qc.invalidateQueries({ queryKey: ["attendance-daily"] });
  }

  const checkIn = useMutation({
    mutationFn: () => apiClient.post("/attendance/check-in", { method: "manual" }),
    onSuccess: (res) => {
      const late = res.data?.late_minutes ?? 0;
      toast.success(late > 0 ? `Checked in — ${late}m late` : "Checked in — on time");
      refreshAll();
    },
    onError: (err) => toast.error(messageFrom(err, "Check-in failed")),
  });
  const checkOut = useMutation({
    mutationFn: () => apiClient.post("/attendance/check-out", {}),
    onSuccess: (res) => {
      const ot = res.data?.overtime_minutes ?? 0;
      toast.success(ot > 0 ? `Checked out — ${ot}m overtime` : "Checked out");
      refreshAll();
    },
    onError: (err) => toast.error(messageFrom(err, "Check-out failed")),
  });
  const breakOn = useMutation({
    mutationFn: () => apiClient.post(`/work-sessions/${session?.id}/break/start`, { break_type_id: null }),
    onSuccess: refreshAll,
    onError: (err) => toast.error(messageFrom(err, "Couldn't start the break")),
  });
  const breakOff = useMutation({
    mutationFn: () => apiClient.post(`/work-sessions/${session?.id}/break/end`),
    onSuccess: refreshAll,
    onError: (err) => toast.error(messageFrom(err, "Couldn't end the break")),
  });

  if (!enabled || collapsed === null) return null;

  const breakPct = Math.min(100, (breakTotal / BREAK_ALLOWANCE_SECONDS) * 100);

  const state = isOnBreak ? "break" : isCheckedIn ? "working" : "offline";
  const statusLabel = isOnBreak ? "ON BREAK" : isCheckedIn ? "WORKING" : "OFFLINE";
  const busy = isLoading || checkIn.isPending || checkOut.isPending || breakOn.isPending || breakOff.isPending;

  function setAndRemember(next: boolean): void {
    setCollapsed(next);
    try { localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0"); } catch { /* storage blocked */ }
  }

  if (collapsed) {
    return (
      <div className="fixed bottom-6 right-6 z-40">
        <button
          type="button"
          className="fw-pill"
          data-state={state}
          data-testid="floating-timer-pill"
          onClick={() => setAndRemember(false)}
          aria-label={`${statusLabel}, work time ${hms(worked)}. Open the timer widget`}
        >
          <span className="fw-status">
            <span className="fw-dot" aria-hidden="true" />
            {statusLabel}
          </span>
          <span className="fw-pill__time">{hms(worked)}</span>
          <ChevronUp size={16} aria-hidden="true" />
        </button>
      </div>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-40" style={{ width: "min(340px, calc(100vw - 32px))" }}>
      <section className="fw-card" data-state={state} aria-label="Check-in and break timer">
        <div className="fw-top">
          <span className="fw-status">
            <span className="fw-dot" aria-hidden="true" />
            <span data-testid="floating-timer-status" aria-live="polite">{statusLabel}</span>
          </span>
          <button
            type="button"
            className="fw-icon-btn"
            onClick={() => setAndRemember(true)}
            aria-label="Minimize timer widget"
            title="Minimize"
            data-testid="floating-timer-minimize"
          >
            <Minus size={13} />
          </button>
        </div>

        <div className="fw-clock">
          <div className="fw-time" role="timer" aria-label="Work time" data-testid="floating-timer-work">
            {hms(worked)}
          </div>
          <div className="fw-label">Work Time</div>
        </div>

        <div>
          <div
            className="fw-progress"
            role="progressbar"
            aria-label="Break time used"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(breakPct)}
            style={{ "--p": `${breakPct.toFixed(2)}%` } as React.CSSProperties}
          >
            <div className="fw-fill" />
          </div>
          <p className="fw-break-text">
            Break Time <b data-testid="floating-timer-break">{hms(breakTotal)}</b>
          </p>
        </div>

        <div className="fw-actions">
          <button
            type="button"
            className={`fw-btn ${isCheckedIn ? "fw-btn--red" : "fw-btn--teal"}`}
            disabled={busy}
            onClick={() => (isCheckedIn ? checkOut.mutate() : checkIn.mutate())}
            data-testid="floating-timer-check"
          >
            <PersonClockIcon />
            <span>{isCheckedIn ? "CHECK OUT" : "CHECK IN"}</span>
          </button>
          <button
            type="button"
            className="fw-btn fw-btn--orange"
            disabled={busy || !isCheckedIn}
            onClick={() => (isOnBreak ? breakOff.mutate() : breakOn.mutate())}
            data-testid="floating-timer-break-button"
          >
            <CoffeeCupIcon />
            <span>{isOnBreak ? "BREAK OFF" : "BREAK ON"}</span>
          </button>
        </div>
      </section>
    </div>
  );
}

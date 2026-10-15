import { useCallback, useEffect, useRef, useState } from "react";
import { Minus, X } from "lucide-react";
import "../styles/floating-widget.css";
import { useTimerStore } from "../store/timerStore";
import { useAttendanceSync } from "../hooks/useAttendanceSync";
import { hasStoredSession } from "../services/authService";
import { formatElapsed } from "../lib/format";
import { CoffeeCupIcon, PersonClockIcon } from "../components/FloatingWidgetIcons";

/**
 * The floating desktop widget (main/index.ts's createWidgetWindow): a small
 * frameless, always-on-top glass card with the work timer, today's break time
 * and the two buttons -- Check In/Check Out and Break On/Break Off. The main
 * process shows it as soon as the app starts.
 *
 * It runs its OWN timerStore instance (separate renderer process). The server's
 * WorkSession is the single source of truth, so the widget:
 *   - loads it on mount, then keeps re-reading it (useAttendanceSync): at once
 *     when the main window changes something (IPC), every few seconds for the
 *     website or another device, and when it is focused / the network returns --
 *     a check-in made anywhere shows up here without anyone touching the widget;
 *   - never blanks the timer on a failed re-read (see timerStore.refresh);
 *   - notices sign-in / sign-out in the main window (both windows share the
 *     same stored tokens) and shows an "Open app" prompt while nobody is
 *     signed in, instead of buttons that could only fail.
 *
 * Minimize (top-right) is a real minimize: the widget stays in the taskbar and
 * is restored from there. Close (the X) hides it to the tray; it returns from the
 * tray menu or the next time the app starts. See main/widgetWindow.ts.
 */

// The thin line under the timer fills as today's break time approaches this.
const BREAK_ALLOWANCE_SECONDS = 60 * 60;

const SIGNED_OUT = {
  status: "idle" as const, sessionId: null, startedAt: null,
  elapsedSeconds: 0, breakSeconds: 0, completedBreakSeconds: 0, breakStartedAt: null,
  todaysBreaks: [], error: null,
};

export default function WidgetScreen(): JSX.Element {
  const {
    status, elapsedSeconds, breakSeconds, completedBreakSeconds, error, busy,
    init, refresh, checkIn, checkOut, startBreak, endBreak, _tick,
  } = useTimerStore();
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval>>();

  // The window is transparent; the page behind the card must be too.
  useEffect(() => {
    document.documentElement.classList.add("fw-window-root");
    return (): void => document.documentElement.classList.remove("fw-window-root");
  }, []);

  useEffect(() => {
    tickRef.current = setInterval(_tick, 1000);
    return (): void => clearInterval(tickRef.current);
  }, [_tick]);

  // First read uses init() (also loads the break types); every later one is a
  // silent refresh() that never blanks a running timer on a network blip.
  const firstLoad = useRef(true);
  const sync = useCallback(async (): Promise<void> => {
    const ok = await hasStoredSession();
    setSignedIn(ok);
    if (!ok) {
      useTimerStore.setState(SIGNED_OUT);
      firstLoad.current = true; // load fresh when someone signs in
      return;
    }
    if (firstLoad.current) {
      firstLoad.current = false;
      await init();
    } else {
      await refresh();
    }
  }, [init, refresh]);

  useEffect(() => {
    void sync();
  }, [sync]);
  useAttendanceSync(sync);

  const isOnBreak = status === "on_break";
  const isCheckedIn = status === "active" || isOnBreak;
  const isLoading = status === "loading";
  const state = isOnBreak ? "break" : isCheckedIn ? "working" : "offline";
  const statusLabel = isOnBreak ? "ON BREAK" : isCheckedIn ? "WORKING" : "OFFLINE";

  const totalBreak = isCheckedIn ? completedBreakSeconds + breakSeconds : 0;
  const breakPct = Math.min(100, (totalBreak / BREAK_ALLOWANCE_SECONDS) * 100);

  return (
    <div style={{ height: "100vh", padding: 14, boxSizing: "border-box" }}>
      <div className="fw-card fw-drag" data-state={state} style={{ height: "100%" }}>
        <div className="fw-top">
          <span className="fw-status">
            <span className="fw-dot" aria-hidden />
            <span data-testid="widget-status-label" aria-live="polite">{statusLabel}</span>
          </span>
          <span className="fw-controls">
            <button
              type="button"
              className="fw-icon-btn"
              onClick={() => void window.ewmp.widget.minimize()}
              data-testid="widget-minimize-button"
              aria-label="Minimize widget"
              title="Minimize to the taskbar"
            >
              <Minus size={13} />
            </button>
            <button
              type="button"
              className="fw-icon-btn"
              onClick={() => void window.ewmp.widget.hide()}
              data-testid="widget-close-button"
              aria-label="Close widget"
              title="Close to the tray — it comes back from the tray menu or the next time the app starts"
            >
              <X size={13} />
            </button>
          </span>
        </div>

        <div className="fw-clock">
          <div className="fw-time" data-testid="widget-working-hours" role="timer" aria-label="Work time">
            {formatElapsed(isCheckedIn ? elapsedSeconds : 0)}
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
            Break Time <b data-testid="widget-break-time">{formatElapsed(totalBreak)}</b>
          </p>
        </div>

        {signedIn === false ? (
          <>
            <p className="fw-note">Sign in to the EWMP app to use the widget.</p>
            <div className="fw-actions fw-actions--single">
              <button
                type="button"
                className="fw-btn fw-btn--teal"
                onClick={() => void window.ewmp.widget.openApp()}
                data-testid="widget-open-app-button"
              >
                <PersonClockIcon />
                <span>OPEN APP</span>
              </button>
            </div>
          </>
        ) : (
          <>
            {error && <p role="alert" className="fw-error">{error}</p>}
            <div className="fw-actions">
              <button
                type="button"
                className={`fw-btn ${isCheckedIn ? "fw-btn--red" : "fw-btn--teal"}`}
                onClick={() => void (isCheckedIn ? checkOut() : checkIn())}
                disabled={isLoading || busy}
                data-testid={isCheckedIn ? "widget-checkout-button" : "widget-checkin-button"}
              >
                <PersonClockIcon />
                <span>{isCheckedIn ? "CHECK OUT" : "CHECK IN"}</span>
              </button>
              <button
                type="button"
                className="fw-btn fw-btn--orange"
                onClick={() => void (isOnBreak ? endBreak() : startBreak())}
                disabled={isLoading || busy || !isCheckedIn}
                data-testid="widget-break-button"
              >
                <CoffeeCupIcon />
                <span>{isOnBreak ? "BREAK OFF" : "BREAK ON"}</span>
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

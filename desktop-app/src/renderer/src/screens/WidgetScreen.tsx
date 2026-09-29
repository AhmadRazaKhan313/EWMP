import { useEffect, useRef } from "react";
import { X, Loader2, LogIn, LogOut, Coffee, Play, Minus } from "lucide-react";
import { useTimerStore } from "../store/timerStore";
import { formatElapsed, formatShortTime } from "../lib/format";
import { cn } from "../components/ui";

/**
 * The floating desktop widget (main/index.ts's createWidgetWindow) — the
 * always-on-top card that stays on the desktop regardless of what else
 * is open. It runs its OWN timerStore instance (separate renderer
 * process) and re-syncs from GET /work-sessions/me/active on mount, same
 * as the main window.
 *
 * REDUCED FROM THREE BUTTONS TO TWO, on request: a Check In/Check Out
 * toggle and a Break/Resume toggle — matching the Clock In card on the
 * dashboard (CheckInWidget.tsx) exactly, rather than the widget having
 * its own separate three-button layout. The ring shows working time and
 * a "since HH:MM" line underneath, same as CheckInWidget's centre — the
 * two surfaces are meant to be read as the same clock, not two designs
 * that happen to share a colour.
 *
 * Minimize/close (top-right) both hide the widget back to the tray,
 * where it can be reopened — a frameless always-on-top widget has no
 * real "minimize to taskbar" concept, so hide-and-reopen-from-tray is
 * the correct behaviour for both, same as Discord's overlay or similar
 * floating widgets. This already works today; nothing about it changes
 * once the app is packaged as an installer — the tray icon is what
 * brings the widget back.
 */

const RING = 108;
const STROKE = 9;
const R = (RING - STROKE) / 2;
const C = 2 * Math.PI * R;
const EXPECTED_SECONDS = 8 * 3600;

export default function WidgetScreen(): JSX.Element {
  const {
    status, elapsedSeconds, breakSeconds, startedAt, error,
    init, checkIn, checkOut, startBreak, endBreak, _tick,
  } = useTimerStore();
  const tickRef = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    void init();
  }, [init]);

  useEffect(() => {
    tickRef.current = setInterval(_tick, 1000);
    return (): void => clearInterval(tickRef.current);
  }, [_tick]);

  const isOnBreak = status === "on_break";
  const isCheckedIn = status === "active" || isOnBreak;
  const isLoading = status === "loading";
  const progress = Math.min(1, elapsedSeconds / EXPECTED_SECONDS);

  const statusLabel = isOnBreak ? "On Break" : isCheckedIn ? "Working" : "Not Checked In";
  const statusDotClass = isOnBreak
    ? "bg-[hsl(var(--warning))]"
    : isCheckedIn
      ? "bg-[hsl(var(--success))] status-dot-pulse"
      : "bg-[hsl(var(--foreground-muted))]";

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-[var(--shadow-md)]">
      {/* Drag handle — the only way to move a frameless window is a CSS
          region the OS chrome-drag protocol recognises; the buttons
          inside it are carved back out with no-drag so they stay
          clickable. */}
      <div
        className="flex shrink-0 items-center justify-between border-b border-[hsl(var(--border))] px-3 py-2"
        style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      >
        <span className="flex items-center gap-1.5">
          <span className={cn("h-1.5 w-1.5 rounded-full", statusDotClass)} aria-hidden />
          <span
            data-testid="widget-status-label"
            className="font-heading text-[11px] font-semibold text-[hsl(var(--foreground-subtle))]"
          >
            {statusLabel}
          </span>
        </span>
        <span className="flex items-center gap-0.5" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
          <button
            onClick={() => void window.ewmp.widget.hide()}
            data-testid="widget-minimize-button"
            aria-label="Minimize widget"
            title="Minimize — reopen from the tray"
            className="flex h-5 w-5 items-center justify-center rounded text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]"
          >
            <Minus size={12} />
          </button>
          <button
            onClick={() => void window.ewmp.widget.hide()}
            data-testid="widget-close-button"
            aria-label="Close widget"
            title="Close — reopen from the tray"
            className="flex h-5 w-5 items-center justify-center rounded text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--destructive-subtle))] hover:text-[hsl(var(--destructive))]"
          >
            <X size={12} />
          </button>
        </span>
      </div>

      {/* Ring — working time + "since HH:MM", exactly what CheckInWidget
          shows at dashboard scale, just smaller. */}
      <div className="flex flex-1 flex-col items-center justify-center gap-1 px-4 py-3">
        <div className="relative" style={{ width: RING, height: RING }}>
          <svg width={RING} height={RING} className="-rotate-90" aria-hidden>
            <circle cx={RING / 2} cy={RING / 2} r={R} fill="none" stroke="hsl(var(--ring-track))" strokeWidth={STROKE} />
            {isCheckedIn && (
              <circle
                cx={RING / 2}
                cy={RING / 2}
                r={R}
                fill="none"
                stroke={isOnBreak ? "hsl(var(--warning))" : "hsl(var(--primary))"}
                strokeWidth={STROKE}
                strokeLinecap="round"
                strokeDasharray={C}
                strokeDashoffset={C * (1 - progress)}
                style={{ transition: "stroke-dashoffset 900ms linear" }}
              />
            )}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 text-center">
            {isLoading ? (
              <Loader2 className="animate-spin text-[hsl(var(--primary))]" size={20} />
            ) : (
              <>
                {isCheckedIn && (
                  <p
                    data-testid="widget-working-hours"
                    className={cn(
                      "num font-heading text-[18px] font-bold leading-none tracking-tight",
                      isOnBreak ? "text-[hsl(var(--warning))]" : "text-[hsl(var(--foreground))]",
                    )}
                  >
                    {formatElapsed(elapsedSeconds)}
                  </p>
                )}
                <p className="max-w-[13ch] text-[8px] font-medium leading-tight text-[hsl(var(--foreground-muted))]">
                  {isCheckedIn && startedAt
                    ? `since ${formatShortTime(new Date(startedAt).toISOString())}`
                    : "Not checked in"}
                </p>
              </>
            )}
          </div>
        </div>

        {isOnBreak && (
          <p data-testid="widget-break-time" className="num text-xs font-semibold text-[hsl(var(--warning))]">
            Break {formatElapsed(breakSeconds)}
          </p>
        )}
      </div>

      {/* Exactly two buttons: Check In/Out toggles itself, Break/Resume
          toggles itself. No third always-visible button. */}
      <div className="grid shrink-0 grid-cols-2 gap-1.5 border-t border-[hsl(var(--border))] p-2">
        {!isCheckedIn ? (
          <button
            onClick={() => void checkIn()}
            disabled={isLoading}
            data-testid="widget-checkin-button"
            title="Check In"
            className="col-span-2 flex items-center justify-center gap-1.5 rounded-[var(--radius-chip)] bg-[hsl(var(--primary))] py-2.5 text-xs font-semibold text-[hsl(var(--primary-foreground))] transition-colors hover:bg-[hsl(var(--primary-hover))] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoading ? <Loader2 className="animate-spin" size={14} /> : <LogIn size={14} />}
            Check In
          </button>
        ) : (
          <>
            <button
              onClick={() => void checkOut()}
              disabled={isLoading}
              data-testid="widget-checkout-button"
              title="Check Out"
              className="flex items-center justify-center gap-1.5 rounded-[var(--radius-chip)] bg-[hsl(var(--destructive))] py-2.5 text-xs font-semibold text-[hsl(var(--destructive-foreground))] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isLoading ? <Loader2 className="animate-spin" size={14} /> : <LogOut size={14} />}
              Check Out
            </button>
            <button
              onClick={() => void (isOnBreak ? endBreak() : startBreak())}
              disabled={isLoading}
              data-testid="widget-break-button"
              title={isOnBreak ? "Resume Work" : "Take Break"}
              className={cn(
                "flex items-center justify-center gap-1.5 rounded-[var(--radius-chip)] py-2.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                isOnBreak
                  ? "bg-[hsl(var(--warning))] text-white hover:opacity-90"
                  : "border border-[hsl(var(--border))] text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))]",
              )}
            >
              {isOnBreak ? <Play size={14} /> : <Coffee size={14} />}
              {isOnBreak ? "Resume" : "Break"}
            </button>
          </>
        )}
      </div>

      {error && (
        <p role="alert" className="px-2 pb-1.5 text-center text-[10px] text-[hsl(var(--destructive))]">
          {error}
        </p>
      )}
    </div>
  );
}

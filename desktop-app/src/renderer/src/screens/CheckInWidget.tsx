import { useEffect, useRef, useState } from "react";
import { Loader2, Coffee, ChevronDown, Play, LogIn, LogOut } from "lucide-react";
import { useTimerStore } from "../store/timerStore";
import { formatElapsed, formatShortTime } from "../lib/format";
import { Badge, Button, cn } from "../components/ui";

/**
 * The Clock In card — a progress RING with the live elapsed time in its
 * centre, matching the admin dashboard's punch donut (grey track, green
 * marker at shift start, red marker at shift end).
 *
 * REPLACES the previous 176px solid circular button. Two reasons that had
 * to go: a giant round button that says "Check Out" gives no sense of how
 * far through the day you are, and the timer underneath it was easy to
 * miss entirely. Here the ring IS the progress indicator and the actions
 * sit below it as normal buttons, so the most-looked-at number on the
 * whole screen is the biggest thing on it.
 *
 * Every data-testid from the old component is preserved — checkin-button,
 * break-button, timer-display, break-label, break-timer-display,
 * break-type-picker, break-type-option-*, break-history.
 */

const RING_SIZE = 236;
const RING_STROKE = 22;
const RADIUS = (RING_SIZE - RING_STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function breakDurationLabel(startedAt: string, endedAt: string | null): string {
  const startMs = new Date(startedAt).getTime();
  const endMs = endedAt ? new Date(endedAt).getTime() : Date.now();
  const minutes = Math.max(0, Math.round((endMs - startMs) / 60000));
  return endedAt ? `${minutes}m` : `${minutes}m (ongoing)`;
}

export default function CheckInWidget({
  /** Hours the shift expects, used only to scale the ring's fill. The
   * ring never exceeds a full turn; past 100% the arc stays full and the
   * overtime badge below it carries the surplus, because a ring that
   * wraps past its own start reads as "back to zero". */
  expectedHours = 8,
}: {
  expectedHours?: number;
} = {}): JSX.Element {
  const {
    status, elapsedSeconds, breakSeconds, startedAt, error, breakTypes, todaysBreaks,
    init, checkIn, checkOut, startBreak, endBreak, _tick,
  } = useTimerStore();
  const tickRef = useRef<ReturnType<typeof setInterval>>();
  const [pickerOpen, setPickerOpen] = useState(false);

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

  const expectedSeconds = Math.max(1, expectedHours * 3600);
  const progress = Math.min(1, elapsedSeconds / expectedSeconds);
  const isOvertime = elapsedSeconds > expectedSeconds;

  const stateLabel = isOnBreak ? "On break" : isCheckedIn ? "Working" : "Not checked in";
  const stateColor = isOnBreak
    ? "hsl(var(--warning))"
    : isCheckedIn
      ? "hsl(var(--success))"
      : "hsl(var(--foreground-muted))";

  function handleBreakButtonClick(): void {
    if (isOnBreak) {
      void endBreak();
      return;
    }
    // Only offer the category picker when the org has configured any
    // (loadBreakTypes fails open to an empty list) — an org with zero
    // break types keeps the original one-click quick pause, never an
    // empty dropdown with nothing in it.
    if (breakTypes.length > 0) {
      setPickerOpen((open) => !open);
    } else {
      void startBreak();
    }
  }

  function pickBreakType(breakTypeId?: string): void {
    setPickerOpen(false);
    void startBreak(breakTypeId);
  }

  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: RING_SIZE, height: RING_SIZE }}>
        <svg width={RING_SIZE} height={RING_SIZE} className="-rotate-90" aria-hidden>
          <circle
            cx={RING_SIZE / 2}
            cy={RING_SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="hsl(var(--ring-track))"
            strokeWidth={RING_STROKE}
          />
          {isCheckedIn && (
            <circle
              cx={RING_SIZE / 2}
              cy={RING_SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke={isOnBreak ? "hsl(var(--warning))" : "hsl(var(--primary))"}
              strokeWidth={RING_STROKE}
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={CIRCUMFERENCE * (1 - progress)}
              style={{ transition: "stroke-dashoffset 900ms linear" }}
            />
          )}
        </svg>

        {/* Shift start / end markers — green at the top of the arc where
            the day begins, red where it should end. Same two dots as the
            admin dashboard's ring. */}
        <span
          className="absolute h-[18px] w-[18px] rounded-full border-[3px] border-[hsl(var(--card))] bg-[hsl(var(--shift-start))]"
          style={{ top: RING_STROKE / 2 - 1, left: RING_SIZE / 2 - 9 }}
          aria-hidden
        />
        <span
          className="absolute h-[18px] w-[18px] rounded-full border-[3px] border-[hsl(var(--card))] bg-[hsl(var(--shift-end))]"
          style={{ bottom: RING_STROKE / 2 - 1, left: RING_SIZE / 2 - 9 }}
          aria-hidden
        />

        <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 text-center">
          {isLoading ? (
            <Loader2 className="animate-spin text-[hsl(var(--primary))]" size={26} />
          ) : (
            <>
              <span className="text-sm font-semibold" style={{ color: stateColor }}>
                {stateLabel}
              </span>
              {isCheckedIn && (
                <p
                  data-testid="timer-display"
                  className={cn(
                    "num font-heading text-[28px] font-bold leading-tight tracking-tight",
                    isOnBreak ? "text-[hsl(var(--warning))]" : "text-[hsl(var(--foreground))]",
                  )}
                >
                  {formatElapsed(elapsedSeconds)}
                </p>
              )}
              <span className="max-w-[16ch] text-[11px] leading-snug text-[hsl(var(--foreground-muted))]">
                {isCheckedIn && startedAt
                  ? `since ${formatShortTime(new Date(startedAt).toISOString())}`
                  : "Start your day when you're ready"}
              </span>
            </>
          )}
        </div>
      </div>

      {isOvertime && (
        <Badge variant="warning" className="mt-3">
          Overtime · {formatElapsed(elapsedSeconds - expectedSeconds)} past {expectedHours}h
        </Badge>
      )}

      {isOnBreak && (
        <div className="mt-3 flex flex-col items-center gap-0.5">
          <p data-testid="break-label" className="text-xs font-medium text-[hsl(var(--warning))]">
            On break — working timer paused
          </p>
          <p
            data-testid="break-timer-display"
            className="num font-heading text-lg font-semibold text-[hsl(var(--warning))]"
          >
            {formatElapsed(breakSeconds)}
          </p>
        </div>
      )}

      <div className="relative mt-5 grid w-full grid-cols-2 gap-2.5">
        {!isCheckedIn ? (
          <Button
            onClick={() => void checkIn()}
            disabled={isLoading}
            data-testid="checkin-button"
            size="lg"
            className="col-span-2"
          >
            {isLoading ? <Loader2 className="animate-spin" size={16} /> : <LogIn size={16} />}
            Check In
          </Button>
        ) : (
          <>
            <Button
              onClick={() => void checkOut()}
              disabled={isLoading}
              data-testid="checkin-button"
              variant="danger"
              size="lg"
            >
              {isLoading ? <Loader2 className="animate-spin" size={16} /> : <LogOut size={16} />}
              Check Out
            </Button>
            <Button
              onClick={handleBreakButtonClick}
              data-testid="break-button"
              variant={isOnBreak ? "warning" : "secondary"}
              size="lg"
              aria-expanded={pickerOpen}
            >
              {isOnBreak ? <Play size={16} /> : <Coffee size={16} />}
              {isOnBreak ? "Resume Work" : "Take Break"}
              {!isOnBreak && breakTypes.length > 0 && <ChevronDown size={14} />}
            </Button>
          </>
        )}

        {pickerOpen && (
          <div
            data-testid="break-type-picker"
            className="absolute right-0 top-full z-10 mt-1.5 w-full max-w-[220px] overflow-hidden rounded-[var(--radius-control)] border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-[var(--shadow-sm)]"
          >
            {breakTypes.map((bt) => (
              <button
                key={bt.id}
                data-testid={`break-type-option-${bt.id}`}
                onClick={() => pickBreakType(bt.id)}
                className="block w-full px-3.5 py-2.5 text-left text-sm text-[hsl(var(--foreground))] hover:bg-[hsl(var(--secondary))]"
              >
                {bt.name}
                {bt.max_minutes && (
                  <span className="ml-1.5 text-xs text-[hsl(var(--foreground-muted))]">({bt.max_minutes}m)</span>
                )}
              </button>
            ))}
            <button
              data-testid="break-type-option-none"
              onClick={() => pickBreakType(undefined)}
              className="block w-full border-t border-[hsl(var(--border))] px-3.5 py-2.5 text-left text-sm text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--secondary))]"
            >
              Quick pause (no category)
            </button>
          </div>
        )}
      </div>

      {isCheckedIn && todaysBreaks.length > 0 && (
        <div data-testid="break-history" className="mt-4 w-full border-t border-[hsl(var(--border))] pt-3">
          <p className="mb-1.5 text-xs font-semibold text-[hsl(var(--foreground-muted))]">Today&apos;s breaks</p>
          <ul className="space-y-1">
            {todaysBreaks.map((b) => (
              <li key={b.id} className="flex justify-between text-xs text-[hsl(var(--foreground-muted))]">
                <span className="num">{formatShortTime(b.started_at)}</span>
                <span className={cn("num", !b.ended_at && "text-[hsl(var(--warning))]")}>
                  {breakDurationLabel(b.started_at, b.ended_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-3 text-xs text-[hsl(var(--destructive))]">
          {error}
        </p>
      )}

      <p className="mt-4 max-w-[30ch] text-center text-[11px] leading-relaxed text-[hsl(var(--foreground-muted))]">
        A physical clock-in can take a few minutes to appear here.
      </p>
    </div>
  );
}

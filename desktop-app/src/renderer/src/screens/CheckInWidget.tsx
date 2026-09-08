import { useEffect, useRef, useState } from "react";
import { Loader2, Coffee, ChevronDown } from "lucide-react";
import { useTimerStore, formatElapsed } from "../store/timerStore";

function breakDurationLabel(startedAt: string, endedAt: string | null): string {
  const startMs = new Date(startedAt).getTime();
  const endMs = endedAt ? new Date(endedAt).getTime() : Date.now();
  const minutes = Math.max(0, Math.round((endMs - startMs) / 60000));
  return endedAt ? `${minutes}m` : `${minutes}m (ongoing)`;
}

export default function CheckInWidget(): JSX.Element {
  const {
    status, elapsedSeconds, error, breakTypes, todaysBreaks,
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

  function handleBreakButtonClick(): void {
    if (isOnBreak) {
      void endBreak();
      return;
    }
    // Phase 5: only offer the category picker when the org has actually
    // configured any (see loadBreakTypes' fail-open-to-empty comment) —
    // an org with zero break types keeps Phase 4's original one-click
    // quick-pause, never an empty dropdown with nothing to pick.
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
    <div className="flex flex-col items-center gap-3 p-6">
      <button
        onClick={() => void (isCheckedIn ? checkOut() : checkIn())}
        disabled={isLoading}
        data-testid="checkin-button"
        className={`w-48 rounded-xl py-4 text-base font-semibold text-white shadow-md transition-colors disabled:opacity-60 ${
          isCheckedIn ? "bg-red-600 hover:bg-red-700" : "bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary-hover))]"
        }`}
      >
        {isLoading ? <Loader2 className="mx-auto animate-spin" size={20} /> : isCheckedIn ? "Check Out" : "Check In"}
      </button>

      {isCheckedIn && (
        <div className="relative w-48">
          <button
            onClick={handleBreakButtonClick}
            data-testid="break-button"
            className={`flex w-48 items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold shadow-sm transition-colors ${
              isOnBreak
                ? "bg-amber-500 text-white hover:bg-amber-600"
                : "border border-[hsl(var(--border))] bg-transparent text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))]"
            }`}
          >
            <Coffee size={16} />
            {isOnBreak ? "Resume Work" : "Take Break"}
            {!isOnBreak && breakTypes.length > 0 && <ChevronDown size={14} />}
          </button>

          {pickerOpen && (
            <div
              data-testid="break-type-picker"
              className="absolute top-full z-10 mt-1 w-full overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-lg"
            >
              {breakTypes.map((bt) => (
                <button
                  key={bt.id}
                  data-testid={`break-type-option-${bt.id}`}
                  onClick={() => pickBreakType(bt.id)}
                  className="block w-full px-4 py-2 text-left text-sm text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))]"
                >
                  {bt.name}
                  {bt.max_minutes && (
                    <span className="ml-1 text-xs text-[hsl(var(--foreground-muted))]">({bt.max_minutes}m)</span>
                  )}
                </button>
              ))}
              <button
                data-testid="break-type-option-none"
                onClick={() => pickBreakType(undefined)}
                className="block w-full border-t border-[hsl(var(--border))] px-4 py-2 text-left text-sm text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--muted))]"
              >
                Quick pause (no category)
              </button>
            </div>
          )}
        </div>
      )}

      {isCheckedIn && (
        <p
          data-testid="timer-display"
          className={`font-mono text-2xl font-bold tabular-nums ${
            isOnBreak ? "text-amber-500" : "text-[hsl(var(--foreground))]"
          }`}
        >
          {formatElapsed(elapsedSeconds)}
        </p>
      )}

      {isOnBreak && (
        <p data-testid="break-label" className="text-xs font-medium text-amber-500">
          On break
        </p>
      )}

      {isCheckedIn && todaysBreaks.length > 0 && (
        <div data-testid="break-history" className="w-48 border-t border-[hsl(var(--border))] pt-2">
          <p className="mb-1 text-xs font-semibold text-[hsl(var(--foreground-muted))]">Today's breaks</p>
          <ul className="space-y-0.5">
            {todaysBreaks.map((b) => (
              <li key={b.id} className="flex justify-between text-xs text-[hsl(var(--foreground-muted))]">
                <span>{new Date(b.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                <span>{breakDurationLabel(b.started_at, b.ended_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <p role="alert" className="text-xs text-[hsl(var(--destructive))]">
          {error}
        </p>
      )}
    </div>
  );
}

import { useEffect, useRef } from "react";
import { Loader2, Coffee } from "lucide-react";
import { useTimerStore, formatElapsed } from "../store/timerStore";

export default function CheckInWidget(): JSX.Element {
  const { status, elapsedSeconds, error, init, checkIn, checkOut, startBreak, endBreak, _tick } = useTimerStore();
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
        <button
          onClick={() => void (isOnBreak ? endBreak() : startBreak())}
          data-testid="break-button"
          className={`flex w-48 items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold shadow-sm transition-colors ${
            isOnBreak
              ? "bg-amber-500 text-white hover:bg-amber-600"
              : "border border-[hsl(var(--border))] bg-transparent text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))]"
          }`}
        >
          <Coffee size={16} />
          {isOnBreak ? "Resume Work" : "Take Break"}
        </button>
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

      {error && (
        <p role="alert" className="text-xs text-[hsl(var(--destructive))]">
          {error}
        </p>
      )}
    </div>
  );
}

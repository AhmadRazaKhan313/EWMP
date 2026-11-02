import { useState } from "react";
import type { BreakLockState } from "../hooks/useBreakLock";
import { mmss } from "../lib/breakPhase";

/** Full-screen cover shown while the break lock is on. */
export default function BreakLockScreen({ state }: { state: BreakLockState }): JSX.Element {
  const [reason, setReason] = useState("");
  const pending = state.requestStatus === "pending";
  const denied = state.requestStatus === "denied";
  return (
    <div
      role="alertdialog"
      aria-label="Break time"
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-6 px-6 text-center text-white"
      style={{ background: "linear-gradient(160deg, hsl(var(--auth-ink)) 0%, hsl(var(--auth-ink-2)) 100%)" }}
    >
      <p className="text-sm uppercase tracking-widest text-white/50">Break time</p>
      <p data-testid="break-countdown" className="font-heading text-7xl font-semibold tabular-nums">{mmss(state.secondsToEnd)}</p>
      <p className="max-w-md text-white/70">
        Your computer is locked for the break. Work time is paused and will restart when the break ends.
      </p>

      {pending ? (
        <p className="rounded-md bg-white/10 px-4 py-2 text-sm">Waiting for your admin to approve…</p>
      ) : (
        <div className="flex w-full max-w-sm flex-col gap-2">
          {denied && <p className="text-sm text-amber-300">Your request was denied. The computer stays locked until the break ends.</p>}
          <textarea
            aria-label="Reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why do you need to keep working? (optional)"
            className="h-20 rounded-md border border-white/20 bg-white/5 p-2 text-sm text-white placeholder:text-white/40"
          />
          <button
            type="button"
            disabled={state.requesting}
            onClick={() => void state.requestUnlock(reason)}
            className="h-10 rounded-md bg-white font-semibold text-black disabled:opacity-50"
          >
            {denied ? "Ask again" : "Request unlock"}
          </button>
          {state.error && <p role="alert" className="text-sm text-red-300">{state.error}</p>}
        </div>
      )}
    </div>
  );
}

/** Slim top banner during the 5 minutes before the break. */
export function BreakWarningBanner({ secondsToStart }: { secondsToStart: number }): JSX.Element {
  return (
    <div role="status" className="fixed inset-x-0 top-0 z-[90] bg-amber-500 px-4 py-1.5 text-center text-sm font-medium text-black">
      Break starts in {mmss(secondsToStart)} — save your work. Your computer will lock.
    </div>
  );
}

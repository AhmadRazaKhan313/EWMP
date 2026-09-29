import { useEffect } from "react";

/**
 * Activity tracking (for social-media/distraction alerts) only runs
 * while genuinely checked in — matches this app's own earlier design
 * note (see the architecture doc's §4): no tracking while idle, no
 * separate on/off switch to build or explain to employees. `status`
 * comes straight from timerStore, so this just mirrors whatever the
 * Check-In widget already shows.
 */
export function useActivityTracking(timerStatus: "loading" | "idle" | "active" | "on_break" | "ended"): void {
  useEffect(() => {
    const shouldTrack = timerStatus === "active" || timerStatus === "on_break";
    if (shouldTrack) {
      void window.ewmp.activity.start();
    } else {
      void window.ewmp.activity.stop();
    }
  }, [timerStatus]);

  // Belt-and-suspenders: if the whole app is closed while still checked
  // in, stop the poll loop rather than leaving a dangling interval in
  // the main process — main/index.ts's window "close" handling already
  // tears down the process itself in the normal case, but this covers
  // any path where the renderer unmounts without that.
  useEffect(() => {
    return (): void => {
      void window.ewmp.activity.stop();
    };
  }, []);
}

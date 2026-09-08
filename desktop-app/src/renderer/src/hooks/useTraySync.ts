import { useEffect } from "react";
import type { TrayIconStatus } from "@shared/deviceTypes";
import { useTimerStore, formatElapsed } from "../store/timerStore";
import { TRAY_STATUS_LABEL } from "@shared/trayStatusLabels";

/**
 * Phase 4 polish item: the tray icon always mirrors the Check-In
 * widget's current state, so an employee can tell "am I clocked in?"
 * from the tray alone, without reopening the window.
 *
 * "loading" (pre-init) and "ended" (unused legacy value — checkOut sets
 * "idle", not "ended") both map to "idle" rather than being treated as
 * distinct tray states; there is no meaningful tray icon for "we
 * haven't checked yet", so it just shows the same dot as "not checked
 * in" until the real status resolves a moment later.
 */
function toTrayStatus(status: ReturnType<typeof useTimerStore.getState>["status"]): TrayIconStatus {
  if (status === "active") return "active";
  if (status === "on_break") return "on_break";
  return "idle";
}

export function useTraySync(): void {
  const timerStatus = useTimerStore((s) => s.status);
  const elapsedSeconds = useTimerStore((s) => s.elapsedSeconds);

  // Full icon+menu rebuild — only when status itself actually changes,
  // never on every tick (see main/index.ts's TRAY_SET_TOOLTIP comment
  // for why that split matters).
  useEffect(() => {
    void window.ewmp.tray.setStatus(toTrayStatus(timerStatus));
  }, [timerStatus]);

  // Mini-timer tooltip — ticks every second while checked in. Idle has
  // no running time to show; applyTrayStatus's own status-change tooltip
  // ("Not checked in") already covers that case, so this effect simply
  // does nothing rather than fighting it with a redundant identical call.
  useEffect(() => {
    const trayStatus = toTrayStatus(timerStatus);
    if (trayStatus === "idle") return;
    void window.ewmp.tray.setTooltip(`EWMP — ${TRAY_STATUS_LABEL[trayStatus]} — ${formatElapsed(elapsedSeconds)}`);
  }, [timerStatus, elapsedSeconds]);
}

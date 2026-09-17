import type { TrayIconStatus } from "./deviceTypes";

/** Human-readable label per status — used for both the tray's context
 * menu header row (main process, see main/trayStatus.ts) and the
 * renderer's mini-timer tooltip text (see useTraySync.ts). Lives here,
 * not in main/trayStatus.ts, because that file imports Electron's
 * main-process-only Menu/Tray APIs at runtime — pulling it into a
 * renderer bundle would break. */
export const TRAY_STATUS_LABEL: Record<TrayIconStatus, string> = {
  idle: "Not checked in",
  active: "Checked in — working",
  on_break: "On break",
};

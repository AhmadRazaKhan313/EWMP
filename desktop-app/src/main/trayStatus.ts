import { Menu, type Tray } from "electron";
import { getTrayIcon } from "./trayIcons";
import type { TrayIconStatus } from "@shared/deviceTypes";
import { TRAY_STATUS_LABEL } from "@shared/trayStatusLabels";

// Re-exported for backward compatibility with existing imports/tests in
// this main-process module; the canonical definition now lives in
// @shared/trayStatusLabels so the renderer's mini-timer tooltip (see
// useTraySync.ts) can use the exact same labels without pulling in
// Electron's main-process-only Menu/Tray APIs.
export { TRAY_STATUS_LABEL };

/**
 * Rebuilds the tray's icon/tooltip/menu for a new timer status. Called
 * from main/index.ts's IPC handler whenever the renderer's timerStore
 * status changes (see App.tsx's tray-sync effect) — the tray always
 * mirrors whatever the Check-In widget currently shows, so glancing at
 * the tray answers "am I clocked in right now?" without opening the
 * window.
 */
export function applyTrayStatus(
  tray: Tray,
  status: TrayIconStatus,
  handlers: { onOpen: () => void; onQuit: () => void },
): void {
  tray.setImage(getTrayIcon(status));
  tray.setToolTip(`EWMP — ${TRAY_STATUS_LABEL[status]}`);
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: TRAY_STATUS_LABEL[status], enabled: false },
      { type: "separator" },
      { label: "Open EWMP", click: handlers.onOpen },
      { type: "separator" },
      { label: "Quit", click: handlers.onQuit },
    ]),
  );
}

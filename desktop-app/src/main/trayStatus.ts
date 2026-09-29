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
 *
 * `unreadCount` (default 0) is passed separately from the status change
 * that triggers this — see main/index.ts's TRAY_SET_BADGE_COUNT handler,
 * which re-calls this with the LAST KNOWN status so a new notification
 * arriving doesn't require (and doesn't wait for) a check-in/out to show
 * up in the tray.
 */
export function applyTrayStatus(
  tray: Tray,
  status: TrayIconStatus,
  handlers: { onOpen: () => void; onQuit: () => void; onToggleWidget?: () => void },
  unreadCount = 0,
  widgetVisible = false,
): void {
  const suffix = unreadCount > 0 ? ` — ${unreadCount} new` : "";
  tray.setImage(getTrayIcon(status));
  tray.setToolTip(`EWMP — ${TRAY_STATUS_LABEL[status]}${suffix}`);
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: TRAY_STATUS_LABEL[status], enabled: false },
      ...(unreadCount > 0
        ? [{ label: `🔔 ${unreadCount} unread notification${unreadCount === 1 ? "" : "s"}`, enabled: false }]
        : []),
      { type: "separator" },
      { label: "Open EWMP", click: handlers.onOpen },
      {
        label: widgetVisible ? "Hide Floating Widget" : "Show Floating Widget",
        click: handlers.onToggleWidget,
        enabled: !!handlers.onToggleWidget,
      },
      { type: "separator" },
      { label: "Quit", click: handlers.onQuit },
    ]),
  );
}

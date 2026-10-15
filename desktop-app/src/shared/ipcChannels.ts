/**
 * Single source of truth for IPC channel names. Both main (registers
 * handlers) and preload (calls them) import from here — never hardcode a
 * channel string in either place, so a typo becomes a compile error
 * instead of a silent runtime no-op.
 */
export const IPC_CHANNELS = {
  SECURE_STORE_GET: "secure-store:get",
  SECURE_STORE_SET: "secure-store:set",
  SECURE_STORE_DELETE: "secure-store:delete",
  SECURE_STORE_CLEAR: "secure-store:clear",
  APP_GET_VERSION: "app:get-version",
  WINDOW_HIDE: "window:hide",
  DEVICE_GET_HARDWARE_INFO: "device:get-hardware-info",
  DEVICE_CAPTURE_SCREENSHOT: "device:capture-screenshot",
  ACTIVITY_START: "activity:start",
  ACTIVITY_STOP: "activity:stop",
  ACTIVITY_SET_WATCHLIST: "activity:set-watchlist",
  ACTIVITY_DRAIN_ALERTS: "activity:drain-alerts",
  TRAY_SET_STATUS: "tray:set-status",
  TRAY_SET_TOOLTIP: "tray:set-tooltip",
  TRAY_SET_BADGE_COUNT: "tray:set-badge-count",
  WIDGET_TOGGLE: "widget:toggle",
  WIDGET_HIDE: "widget:hide",
  WIDGET_IS_VISIBLE: "widget:is-visible",
  WIDGET_OPEN_APP: "widget:open-app",
  WIDGET_MINIMIZE: "widget:minimize",
  /** renderer -> main: "I changed the attendance state on the server". */
  ATTENDANCE_NOTIFY_CHANGED: "attendance:notify-changed",
  /** main -> every other renderer: "re-read the attendance state now". */
  ATTENDANCE_CHANGED: "attendance:changed",
} as const;

export type IpcChannel = (typeof IPC_CHANNELS)[keyof typeof IPC_CHANNELS];

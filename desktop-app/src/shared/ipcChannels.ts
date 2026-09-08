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
  TRAY_SET_STATUS: "tray:set-status",
  TRAY_SET_TOOLTIP: "tray:set-tooltip",
} as const;

export type IpcChannel = (typeof IPC_CHANNELS)[keyof typeof IPC_CHANNELS];

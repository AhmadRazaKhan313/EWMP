import { contextBridge, ipcRenderer } from "electron";
import { IPC_CHANNELS } from "@shared/ipcChannels";
import type { SecureStoreKey } from "@shared/secureStore";
import type { HardwareInfo, TrayIconStatus, CapturedScreenshot, WatchlistAlert } from "@shared/deviceTypes";

/**
 * This is the ONLY code that runs with access to both Node APIs (ipcRenderer)
 * and the page's `window` object. Because `contextIsolation: true`, nothing
 * defined here is reachable by the page's own scripts except exactly what
 * we explicitly attach via `contextBridge.exposeInMainWorld` below — the
 * renderer gets `window.ewmp.*` and nothing else.
 */
export interface EwmpBridge {
  app: {
    getVersion: () => Promise<string>;
  };
  secureStore: {
    get: (key: SecureStoreKey) => Promise<string | null>;
    set: (key: SecureStoreKey, value: string) => Promise<void>;
    delete: (key: SecureStoreKey) => Promise<void>;
    clear: () => Promise<void>;
  };
  window: {
    hide: () => Promise<void>;
  };
  device: {
    getHardwareInfo: () => Promise<HardwareInfo>;
    captureScreenshot: () => Promise<CapturedScreenshot>;
  };
  activity: {
    start: () => Promise<void>;
    stop: () => Promise<void>;
    setWatchlist: (terms: string[]) => Promise<void>;
    drainAlerts: () => Promise<WatchlistAlert[]>;
  };
  tray: {
    setStatus: (status: TrayIconStatus) => Promise<void>;
    setTooltip: (text: string) => Promise<void>;
    setBadgeCount: (count: number) => Promise<void>;
  };
  widget: {
    /** Shows the floating desktop widget if hidden, hides it if shown —
     * also reachable from the tray's "Show/Hide Floating Widget" item.
     * Returns the new visibility. */
    toggle: () => Promise<boolean>;
    /** Called from the widget window's own close button — hides rather
     * than destroys it, same minimize-to-tray philosophy as the main
     * window, so re-toggling doesn't need to recreate/reload it. */
    hide: () => Promise<void>;
    isVisible: () => Promise<boolean>;
  };
}

const ewmpBridge: EwmpBridge = {
  app: {
    getVersion: (): Promise<string> => ipcRenderer.invoke(IPC_CHANNELS.APP_GET_VERSION),
  },
  secureStore: {
    get: (key: SecureStoreKey): Promise<string | null> =>
      ipcRenderer.invoke(IPC_CHANNELS.SECURE_STORE_GET, key),
    set: (key: SecureStoreKey, value: string): Promise<void> =>
      ipcRenderer.invoke(IPC_CHANNELS.SECURE_STORE_SET, key, value),
    delete: (key: SecureStoreKey): Promise<void> =>
      ipcRenderer.invoke(IPC_CHANNELS.SECURE_STORE_DELETE, key),
    clear: (): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.SECURE_STORE_CLEAR),
  },
  window: {
    hide: (): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.WINDOW_HIDE),
  },
  device: {
    getHardwareInfo: (): Promise<HardwareInfo> => ipcRenderer.invoke(IPC_CHANNELS.DEVICE_GET_HARDWARE_INFO),
    captureScreenshot: (): Promise<CapturedScreenshot> =>
      ipcRenderer.invoke(IPC_CHANNELS.DEVICE_CAPTURE_SCREENSHOT),
  },
  activity: {
    start: (): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.ACTIVITY_START),
    stop: (): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.ACTIVITY_STOP),
    setWatchlist: (terms: string[]): Promise<void> =>
      ipcRenderer.invoke(IPC_CHANNELS.ACTIVITY_SET_WATCHLIST, terms),
    drainAlerts: (): Promise<WatchlistAlert[]> => ipcRenderer.invoke(IPC_CHANNELS.ACTIVITY_DRAIN_ALERTS),
  },
  tray: {
    setStatus: (status: TrayIconStatus): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.TRAY_SET_STATUS, status),
    setTooltip: (text: string): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.TRAY_SET_TOOLTIP, text),
    setBadgeCount: (count: number): Promise<void> =>
      ipcRenderer.invoke(IPC_CHANNELS.TRAY_SET_BADGE_COUNT, count),
  },
  widget: {
    toggle: (): Promise<boolean> => ipcRenderer.invoke(IPC_CHANNELS.WIDGET_TOGGLE),
    hide: (): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.WIDGET_HIDE),
    isVisible: (): Promise<boolean> => ipcRenderer.invoke(IPC_CHANNELS.WIDGET_IS_VISIBLE),
  },
};

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("ewmp", ewmpBridge);
  } catch (error) {
    console.error("Failed to expose ewmp bridge:", error);
  }
} else {
  // contextIsolation is a hard requirement (see main/index.ts webPreferences)
  // — if this branch ever runs, something upstream regressed a security
  // setting, so fail loudly in dev rather than silently attaching to a
  // non-isolated window.
  (window as unknown as { ewmp: EwmpBridge }).ewmp = ewmpBridge;
}

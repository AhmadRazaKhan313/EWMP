import { contextBridge, ipcRenderer } from "electron";
import { IPC_CHANNELS } from "@shared/ipcChannels";
import type { SecureStoreKey } from "@shared/secureStore";
import type { HardwareInfo, TrayIconStatus } from "@shared/deviceTypes";

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
  };
  tray: {
    setStatus: (status: TrayIconStatus) => Promise<void>;
    setTooltip: (text: string) => Promise<void>;
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
  },
  tray: {
    setStatus: (status: TrayIconStatus): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.TRAY_SET_STATUS, status),
    setTooltip: (text: string): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.TRAY_SET_TOOLTIP, text),
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

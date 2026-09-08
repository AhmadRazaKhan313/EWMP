import { app, BrowserWindow, session, shell, Tray, ipcMain } from "electron";
import { join } from "path";
import { is } from "@electron-toolkit/utils";
import { IPC_CHANNELS } from "@shared/ipcChannels";
import {
  getSecureValue,
  setSecureValue,
  deleteSecureValue,
  clearSecureStore,
  type SecureStoreKey,
} from "@shared/secureStore";
import { getHardwareInfo } from "./hardwareInfo";
import { applyTrayStatus } from "./trayStatus";
import { getTrayIcon } from "./trayIcons";
import type { TrayIconStatus } from "@shared/deviceTypes";

// ── Single instance lock ─────────────────────────────────────────────────────
// A timer/attendance app must never run as two separate processes — that
// would double-count elapsed time and could race on the same local token
// store. Second launch attempts just focus the existing window instead.
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let isQuitting = false;

// Some machines (older/virtual GPU drivers, remote desktop sessions, some
// laptops with hybrid graphics) fail to initialize Chromium's GPU process.
// That shows up as a persistent black/white blank window with nothing
// rendered and no visible error in the UI. Disabling hardware acceleration
// avoids that entire class of failure; this app has no need for GPU-heavy
// rendering anyway.
app.disableHardwareAcceleration();

const isDev = is.dev;
const RENDERER_URL = process.env["ELECTRON_RENDERER_URL"];

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 420,
    height: 640,
    minWidth: 360,
    minHeight: 480,
    show: false,
    autoHideMenuBar: true,
    title: "EWMP",
    webPreferences: {
      // Security hardening (Phase 1 DoD): the renderer never gets direct
      // Node access. All privileged calls go through the narrow, typed
      // bridge in src/preload/index.ts via contextBridge.
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  window.on("ready-to-show", () => {
    window.show();
  });

  // Minimize-to-tray, not quit (Phase 8 builds this out fully) — the timer
  // must keep running when the window is closed, only actually exiting on
  // an explicit Quit from the tray menu or OS shutdown.
  window.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      window.hide();
    }
  });

  // Any attempt to open a new window (target=_blank, window.open, etc.)
  // opens in the OS default browser instead — the app never hosts a second
  // Chromium window pointed at arbitrary content.
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev && RENDERER_URL) {
    void window.loadURL(RENDERER_URL);
  } else {
    void window.loadFile(join(__dirname, "../renderer/index.html"));
  }

  return window;
}

function createTray(window: BrowserWindow): Tray {
  const trayInstance = new Tray(getTrayIcon("idle"));
  applyTrayStatus(trayInstance, "idle", {
    onOpen: () => window.show(),
    onQuit: () => {
      isQuitting = true;
      app.quit();
    },
  });
  trayInstance.on("click", () => {
    window.isVisible() ? window.hide() : window.show();
  });
  return trayInstance;
}

app.on("second-instance", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
});

app.whenReady().then(() => {
  // ── IPC handlers ────────────────────────────────────────────────────────
  // Only these specific, narrow operations are reachable from the
  // renderer — never a generic "run this Node code" channel.
  ipcMain.handle(IPC_CHANNELS.SECURE_STORE_GET, (_event, key: SecureStoreKey) =>
    getSecureValue(key),
  );
  ipcMain.handle(IPC_CHANNELS.SECURE_STORE_SET, (_event, key: SecureStoreKey, value: string) =>
    setSecureValue(key, value),
  );
  ipcMain.handle(IPC_CHANNELS.SECURE_STORE_DELETE, (_event, key: SecureStoreKey) =>
    deleteSecureValue(key),
  );
  ipcMain.handle(IPC_CHANNELS.SECURE_STORE_CLEAR, () => clearSecureStore());
  ipcMain.handle(IPC_CHANNELS.APP_GET_VERSION, () => app.getVersion());
  ipcMain.handle(IPC_CHANNELS.WINDOW_HIDE, () => mainWindow?.hide());
  // Phase 4 item #1 (self-enrollment): the renderer has no Node access
  // (nodeIntegration: false), so hostname/CPU/RAM/MAC — all only readable
  // via Node's `os` module — have to be collected here and handed over,
  // same narrow-bridge pattern as everything else in this file.
  ipcMain.handle(IPC_CHANNELS.DEVICE_GET_HARDWARE_INFO, () => getHardwareInfo());
  // Phase 4 polish: the tray icon mirrors whatever the renderer's
  // timerStore currently shows — see App.tsx's tray-sync effect, which
  // is the only caller. Silently no-ops if the tray hasn't been created
  // yet (there's a brief window between app.whenReady() and createTray()
  // below) rather than throwing, since a missed tray update for one
  // status change is harmless — the next status change corrects it.
  ipcMain.handle(IPC_CHANNELS.TRAY_SET_STATUS, (_event, status: TrayIconStatus) => {
    if (!mainWindow || !tray) return;
    applyTrayStatus(tray, status, {
      onOpen: () => mainWindow?.show(),
      onQuit: () => {
        isQuitting = true;
        app.quit();
      },
    });
  });
  // Split from TRAY_SET_STATUS deliberately: this fires every second
  // while checked in (the "mini-timer" requirement), and only touches
  // setToolTip — never setContextMenu. Rebuilding the context menu that
  // often would be wasteful, and if the employee has it open via
  // right-click at that instant, replacing it out from under them could
  // dismiss or glitch it. Tooltip text has no such risk.
  ipcMain.handle(IPC_CHANNELS.TRAY_SET_TOOLTIP, (_event, text: string) => {
    tray?.setToolTip(text);
  });

  // Content-Security-Policy on every response, not just the initial HTML —
  // blocks any remote script from ever executing in this app's windows,
  // regardless of what page (dev server or packaged file) is loaded.
  //
  // Bug fix: this used to omit `connect-src` entirely, which per the CSP
  // spec makes it fall back to `default-src 'self'` — silently blocking
  // EVERY fetch/XHR call to anything other than the app's own origin.
  // Since the backend server address is admin-configured at runtime (see
  // ServerSetupScreen) and isn't known at build time, `connect-src` can't
  // be scoped to one specific host — it has to allow the schemes the
  // configured server could use. `script-src`/`style-src` stay tightly
  // scoped to `'self'` (styles need 'unsafe-inline' for Tailwind), so this
  // does NOT reopen the door to remote/injected script execution — it
  // only affects where this app's own first-party code can send requests.
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [
          [
            "default-src 'self'",
            // Vite's dev server needs 'unsafe-eval' for HMR module evaluation
            // AND 'unsafe-inline' for the React Fast Refresh preamble script
            // it injects into the page — neither is needed (or present) in
            // the packaged production build, which only ever runs this
            // app's own hashed, external script files.
            "script-src 'self'" + (isDev ? " 'unsafe-eval' 'unsafe-inline'" : ""),
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "connect-src 'self' http://*:* https://*:* ws://*:* wss://*:*",
          ].join("; "),
        ],
      },
    });
  });

  mainWindow = createWindow();
  tray = createTray(mainWindow);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      mainWindow = createWindow();
    } else {
      mainWindow?.show();
    }
  });
});

app.on("before-quit", () => {
  isQuitting = true;
});

app.on("window-all-closed", () => {
  // Deliberately NOT quitting here (even on non-macOS): closing the window
  // hides to tray (see the 'close' handler above) — the app only exits via
  // the tray's Quit item or before-quit/OS shutdown.
});

// Silence unused-var lint on `tray` — it's kept alive intentionally so it
// isn't garbage-collected (Electron requires a live reference to the Tray
// instance for its icon to keep showing).
void tray;

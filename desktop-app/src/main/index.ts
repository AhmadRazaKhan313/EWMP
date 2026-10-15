import { app, BrowserWindow, session, screen, shell, Tray, ipcMain } from "electron";
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
import { captureScreenshot } from "./screenshotCapture";
import {
  startActivityTracking,
  stopActivityTracking,
  setActivityWatchlist,
  drainPendingAlerts,
} from "./activityTracker";
import { applyTrayStatus } from "./trayStatus";
import { relayToOtherWindows } from "./attendanceBroadcast";
import {
  createWidgetWindowManager,
  WIDGET_HEIGHT,
  WIDGET_WIDTH,
  type WidgetWindowLike,
} from "./widgetWindow";
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

// The one floating widget window: created on first use, reused for the life of
// the app, minimized to the taskbar / closed to the tray (widgetWindow.ts).
const widget = createWidgetWindowManager({
  create: () => createWidgetBrowserWindow() as unknown as WidgetWindowLike,
  workAreas: () => {
    const primary = screen.getPrimaryDisplay();
    const others = screen.getAllDisplays().filter((d) => d.id !== primary.id);
    return [primary, ...others].map((d) => d.workArea);
  },
  isQuitting: () => isQuitting,
  onStateChange: () => rebuildTrayMenu(),
  log: (message) => console.log(message),
});
// Tracked so TRAY_SET_BADGE_COUNT (fired on its own polling cadence — see
// useNotificationBadge.ts) can rebuild the tray tooltip/menu with the
// CURRENT status without needing a check-in/out to also happen first.
let currentTrayStatus: TrayIconStatus = "idle";
let currentUnreadCount = 0;

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
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 700,
    center: true,
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

/**
 * The floating "always visible on the desktop" widget requested
 * alongside the auto-checkout work: a small, frameless, always-on-top
 * window showing live working-hours/break-time and just the two toggle
 * buttons (Check In/Check Out, Take Break/Resume) — no other chrome.
 * It loads the SAME renderer bundle as the main window (same preload,
 * same auth tokens via secureStore, same /work-sessions endpoints) with
 * a `?widget=1` query flag; App.tsx renders WidgetScreen instead of the
 * normal login/dashboard flow whenever that flag is present. Because
 * it's a genuinely separate renderer process, its own timerStore
 * instance re-syncs from the server on load rather than sharing state
 * with the main window in memory — the two stay consistent because both
 * ultimately read/write the one server-side WorkSession, not because
 * they share any client-side state.
 */
/**
 * Builds the widget's BrowserWindow: a small frameless, transparent, always-on-top
 * card. Its LIFECYCLE -- create once, minimize, hide to the tray, restore -- is
 * handled by widgetWindow.ts; this only configures the window.
 *
 * The window is the glass card plus 14px of transparent margin on every side,
 * which is where the card's CSS drop shadow is drawn (a transparent window has
 * no OS shadow of its own on Windows, and one on macOS would double up).
 */
function createWidgetBrowserWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: WIDGET_WIDTH,
    height: WIDGET_HEIGHT,
    show: false,
    title: "EWMP Widget",
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    resizable: false,
    maximizable: false,
    minimizable: true,
    fullscreenable: false,
    alwaysOnTop: true,
    // In the taskbar (and Alt+Tab) while it is shown or minimized -- that is
    // how a minimized widget gets restored. (It was `true` before, which
    // meant the widget had no taskbar button at all, ever.)
    skipTaskbar: false,
    hasShadow: false,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  // "screen-saver" level keeps it above fullscreen apps too on macOS, where the
  // default "floating" level does not.
  window.setAlwaysOnTop(true, "screen-saver");

  // A transparent, frameless window that fails to load looks exactly like "the
  // widget never appeared" -- so say what happened in the terminal.
  window.webContents.on("did-fail-load", (_event, code, description, url) => {
    console.error(`[widget] failed to load ${url}: ${description} (${code})`);
  });
  window.webContents.on("render-process-gone", (_event, details) => {
    console.error(`[widget] renderer process exited: ${details.reason}`);
  });
  window.webContents.on("preload-error", (_event, path, error) => {
    console.error(`[widget] preload script failed (${path}): ${error.message}`);
  });

  if (isDev && RENDERER_URL) {
    void window.loadURL(RENDERER_URL + "?widget=1");
  } else {
    void window.loadFile(join(__dirname, "../renderer/index.html"), { search: "widget=1" });
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
    onToggleWidget: () => {
      widget.toggle();
      rebuildTrayMenu();
    },
  });
  trayInstance.on("click", () => {
    window.isVisible() ? window.hide() : window.show();
  });
  return trayInstance;
}

/** Rebuilds the tray menu with the CURRENT status/unread/widget-visible
 * values — called after anything that should be reflected in the menu
 * next time it's opened (a status change, an unread-count change, or a
 * widget toggle) without needing three near-duplicate call sites to stay
 * in sync by hand. */
function rebuildTrayMenu(): void {
  if (!mainWindow || !tray) return;
  applyTrayStatus(
    tray,
    currentTrayStatus,
    {
      onOpen: () => mainWindow?.show(),
      onQuit: () => {
        isQuitting = true;
        app.quit();
      },
      onToggleWidget: () => {
        widget.toggle();
        rebuildTrayMenu();
      },
    },
    currentUnreadCount,
    widget.isShown(),
  );
}

app.on("second-instance", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
  // Launching the app again also brings the floating widget back if it was
  // hidden -- "the widget is on screen whenever the app is on" shouldn't
  // depend on remembering the tray menu.
  if (app.isReady() && !widget.isShown()) {
    widget.open({ focus: false });   // restores it if it was minimized, shows it if hidden
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
  ipcMain.handle(IPC_CHANNELS.DEVICE_CAPTURE_SCREENSHOT, () => captureScreenshot());
  // Activity tracking (social-media/distraction alerts) — see
  // activityTracker.ts's top-of-file note on why every one of these is a
  // synchronous, side-effect-only call with no network/async work of its
  // own: the renderer owns the heartbeat cadence and the actual upload,
  // this module only tracks local in-memory state between beats.
  ipcMain.handle(IPC_CHANNELS.ACTIVITY_START, () => startActivityTracking());
  ipcMain.handle(IPC_CHANNELS.ACTIVITY_STOP, () => stopActivityTracking());
  ipcMain.handle(IPC_CHANNELS.ACTIVITY_SET_WATCHLIST, (_event, terms: string[]) => setActivityWatchlist(terms));
  ipcMain.handle(IPC_CHANNELS.ACTIVITY_DRAIN_ALERTS, () => drainPendingAlerts());
  // Phase 4 polish: the tray icon mirrors whatever the renderer's
  // timerStore currently shows — see App.tsx's tray-sync effect, which
  // is the only caller. Silently no-ops if the tray hasn't been created
  // yet (there's a brief window between app.whenReady() and createTray()
  // below) rather than throwing, since a missed tray update for one
  // status change is harmless — the next status change corrects it.
  ipcMain.handle(IPC_CHANNELS.TRAY_SET_STATUS, (_event, status: TrayIconStatus) => {
    if (!mainWindow || !tray) return;
    currentTrayStatus = status;
    rebuildTrayMenu();
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
  // Notifications badge: the renderer polls GET /notifications/unread-count
  // (see hooks/useNotificationBadge.ts) and pushes the number here. Two
  // things happen with it:
  //   1. app.setBadgeCount — the OS-native dock/taskbar badge. Only
  //      actually renders on macOS and Linux (Unity); it's a documented
  //      silent no-op (returns false) on Windows and unsupported desktop
  //      environments, so this is never wrapped in a platform check.
  //   2. The tray tooltip/menu is rebuilt via the same applyTrayStatus
  //      used by TRAY_SET_STATUS, so Windows users (no dock badge) still
  //      get a visible cue — "🔔 N unread notifications" in the tray's
  //      right-click menu, and the tooltip on hover.
  ipcMain.handle(IPC_CHANNELS.TRAY_SET_BADGE_COUNT, (_event, count: number) => {
    currentUnreadCount = Math.max(0, count);
    app.setBadgeCount(currentUnreadCount);
    rebuildTrayMenu();
  });

  // Floating desktop widget (auto-checkout feature set): a small
  // always-on-top window with just Check In/Out + Break/Resume — see
  // createWidgetWindow's docstring. Toggled from the tray menu; also
  // hideable from its own in-widget close button (WIDGET_HIDE).
  ipcMain.handle(IPC_CHANNELS.WIDGET_TOGGLE, () => {
    const shown = widget.toggle();
    rebuildTrayMenu();
    return shown;
  });
  // The widget's X: hide to the tray (the window is kept, see widgetWindow.ts).
  ipcMain.handle(IPC_CHANNELS.WIDGET_HIDE, () => widget.hide());
  // The widget's "minimize": a real minimize, so it stays in the taskbar.
  ipcMain.handle(IPC_CHANNELS.WIDGET_MINIMIZE, () => widget.minimize());
  ipcMain.handle(IPC_CHANNELS.WIDGET_IS_VISIBLE, () => widget.isShown());

  // Attendance changed in one window (check in/out, break on/off): nudge every
  // OTHER window to re-read the server now. Registered once, here, so the
  // handler can't be added twice however many windows are opened.
  ipcMain.on(IPC_CHANNELS.ATTENDANCE_NOTIFY_CHANGED, (event) => {
    relayToOtherWindows(
      BrowserWindow.getAllWindows().map((w) => ({
        id: w.webContents.id,
        isDestroyed: () => w.isDestroyed() || w.webContents.isDestroyed(),
        send: (channel: string) => w.webContents.send(channel),
      })),
      event.sender.id,
      IPC_CHANNELS.ATTENDANCE_CHANGED,
    );
  });
  // "Open app" on the widget (shown while nobody is signed in): bring the main
  // window forward, restoring it if it was minimized or hidden to the tray.
  ipcMain.handle(IPC_CHANNELS.WIDGET_OPEN_APP, () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
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

  // The floating widget is on screen as soon as the app is on -- the user
  // does not have to find the tray menu first. Hiding it (its X button or the
  // tray item) lasts until the next launch.
  //
  // Shown BEFORE the tray is created, and guarded: nothing that goes wrong
  // while building the tray may be able to keep the widget off the screen.
  console.log("[ewmp] app ready -- showing the floating widget");
  try {
    widget.open({ focus: false });
  } catch (err) {
    console.error("[widget] could not be shown:", err);
  }

  tray = createTray(mainWindow);
  rebuildTrayMenu();

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

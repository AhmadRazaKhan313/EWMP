/**
 * Break-time lock (K-01) — main-process side.
 *
 * While the renderer says the break is on and nobody has approved an unlock, the main
 * window covers the whole screen, stays on top, cannot be closed/minimised and takes
 * focus back if it loses it. The floating widget is hidden so it can't be used as a
 * way around the lock. Unlocking restores everything exactly as it was.
 *
 * (An OS-level lock like LockWorkStation would need the employee's password to get
 * back in, which defeats "unlock only when the admin approves" — this is an app-level
 * cover on purpose.)
 */
export const BREAK_LOCK_CHANNEL = "break-lock:set";

export interface LockableWindow {
  isDestroyed(): boolean;
  show(): void;
  focus(): void;
  restore(): void;
  isMinimized(): boolean;
  setFullScreen(flag: boolean): void;
  setAlwaysOnTop(flag: boolean, level?: string): void;
  setClosable(flag: boolean): void;
  setMinimizable(flag: boolean): void;
  on(event: string, listener: (...args: unknown[]) => void): unknown;
  removeListener(event: string, listener: (...args: unknown[]) => void): unknown;
}

export interface LockableWidget {
  isShown(): boolean;
  hide(): void;
  open(opts?: { focus?: boolean }): void;
}

export interface BreakLockController {
  setLocked(locked: boolean): void;
  isLocked(): boolean;
}

export function createBreakLockController(deps: {
  getWindow: () => LockableWindow | null;
  widget?: LockableWidget;
}): BreakLockController {
  let locked = false;
  let widgetWasShown = false;
  let attached: { win: LockableWindow; onBlur: () => void; onMin: () => void } | null = null;

  const release = (): void => {
    if (attached) {
      const { win, onBlur, onMin } = attached;
      attached = null;
      if (!win.isDestroyed()) {
        win.removeListener("blur", onBlur);
        win.removeListener("minimize", onMin);
        win.setAlwaysOnTop(false);
        win.setFullScreen(false);
        win.setClosable(true);
        win.setMinimizable(true);
      }
    }
    if (widgetWasShown) deps.widget?.open({ focus: false });
    widgetWasShown = false;
  };

  return {
    isLocked: () => locked,
    setLocked(next: boolean): void {
      if (next === locked) return;
      locked = next;
      if (!next) return release();

      const win = deps.getWindow();
      if (!win || win.isDestroyed()) {
        locked = false; // nothing to lock; the renderer will ask again
        return;
      }
      widgetWasShown = deps.widget?.isShown() ?? false;
      if (widgetWasShown) deps.widget?.hide();
      win.setClosable(false);
      win.setMinimizable(false);
      win.show();
      win.setFullScreen(true);
      win.setAlwaysOnTop(true, "screen-saver");
      win.focus();
      const onBlur = (): void => { if (locked && !win.isDestroyed()) win.focus(); };
      const onMin = (): void => { if (locked && !win.isDestroyed()) win.restore(); };
      win.on("blur", onBlur);
      win.on("minimize", onMin);
      attached = { win, onBlur, onMin };
    },
  };
}

export function registerBreakLockIpc(
  ipc: { handle: (channel: string, fn: (event: unknown, locked: boolean) => void) => void },
  controller: BreakLockController,
): void {
  ipc.handle(BREAK_LOCK_CHANNEL, (_e, locked) => controller.setLocked(Boolean(locked)));
}

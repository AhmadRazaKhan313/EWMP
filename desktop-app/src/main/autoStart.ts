/**
 * Start with Windows (and macOS), quietly in the tray.
 *
 * Device management (lock, screenshot, alerts, online status) only works while
 * the app is running, so the app registers itself to start when the employee
 * signs in to the computer. That launch passes --hidden: the tray icon and the
 * floating widget come up, the big window does not pop open.
 *
 * Only a packaged build registers itself. A dev run would otherwise register
 * the bare electron.exe as a startup program.
 */
export const HIDDEN_FLAG = "--hidden";

export interface LoginItemOptions {
  openAtLogin: boolean;
  openAsHidden?: boolean;
  args?: string[];
}

export function loginItemOptions(isPackaged: boolean, platform: string): LoginItemOptions | null {
  if (!isPackaged) return null;
  if (platform !== "win32" && platform !== "darwin") return null;
  return { openAtLogin: true, openAsHidden: true, args: [HIDDEN_FLAG] };
}

/** True when the OS started the app at sign-in (or --hidden was passed). */
export function shouldStartHidden(argv: readonly string[], wasOpenedAtLogin: boolean): boolean {
  return argv.includes(HIDDEN_FLAG) || wasOpenedAtLogin;
}

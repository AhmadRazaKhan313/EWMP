/**
 * Lifecycle of the floating widget window.
 *
 * The rules (and why they exist):
 *
 *  - ONE window. It is created the first time it is needed and then reused for
 *    the life of the app: hiding it keeps the window (and its loaded page and
 *    timers) alive, so showing it again is instant and can never produce a
 *    second widget.
 *  - MINIMIZE is a real minimize. The window keeps a taskbar button, so it can
 *    be restored from the taskbar like any Windows app. (It used to be created
 *    with skipTaskbar and its "minimize" button just hid it, which left the
 *    user with no taskbar entry and only a tray icon -- hidden in Windows'
 *    overflow flyout -- to get it back.)
 *  - CLOSE (the X, Alt+F4) hides the widget to the tray, exactly like the main
 *    window does. It is not destroyed. The tray menu, relaunching the app, or
 *    the widget's own tray item bring it back. Only quitting the app destroys it.
 *  - Whether the widget is "shown" is always READ from the window, never kept as
 *    a separate flag, and every window event (show / hide / minimize / restore)
 *    notifies the tray so its menu label cannot go stale.
 *  - It is placed bottom-right once, then left where the user drags it; it is
 *    only moved again if its display went away and it ended up off every screen.
 *
 * Written against a minimal window interface (see WidgetWindowLike) so this
 * logic is unit-tested without Electron; index.ts passes a real BrowserWindow.
 */

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface WidgetWindowLike {
  isDestroyed(): boolean;
  isVisible(): boolean;
  isMinimized(): boolean;
  show(): void;
  showInactive(): void;
  hide(): void;
  minimize(): void;
  restore(): void;
  focus(): void;
  setPosition(x: number, y: number): void;
  getBounds(): Rect;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  on(event: string, listener: (...args: any[]) => void): unknown;
}

export interface WidgetWindowDeps {
  /** Builds the real window. Called only when there is no live one. */
  create(): WidgetWindowLike;
  /** Usable area of every display; the primary display first. */
  workAreas(): Rect[];
  isQuitting(): boolean;
  /** Something the tray menu shows has changed (shown / hidden / minimized). */
  onStateChange(): void;
  log?(message: string): void;
}

export const WIDGET_WIDTH = 352;
export const WIDGET_HEIGHT = 372;
const EDGE_GAP = 2;
// A window counts as "on screen" if at least this much of it overlaps a display.
const MIN_VISIBLE_PX = 48;

export interface WidgetWindowManager {
  /** Show the widget (restoring it if minimized). `focus: false` is for app
   * start, where it must appear without stealing the keyboard. */
  open(options?: { focus?: boolean }): void;
  /** Close/X: hide to the tray (kept alive). */
  hide(): void;
  /** Real minimize (stays in the taskbar). */
  minimize(): void;
  /** Tray item: minimized -> restore, shown -> hide, hidden -> show. Returns
   * whether the widget is shown afterwards. */
  toggle(): boolean;
  /** Visible and not minimized. */
  isShown(): boolean;
  isMinimized(): boolean;
}

export function createWidgetWindowManager(deps: WidgetWindowDeps): WidgetWindowManager {
  let win: WidgetWindowLike | null = null;
  let placed = false;

  const live = (): WidgetWindowLike | null => (win && !win.isDestroyed() ? win : null);

  function ensureWindow(): WidgetWindowLike {
    const existing = live();
    if (existing) return existing;

    const created = deps.create();
    win = created;
    placed = false;

    for (const event of ["show", "hide", "minimize", "restore"]) {
      created.on(event, () => deps.onStateChange());
    }
    created.on("close", (event: { preventDefault(): void }) => {
      if (!deps.isQuitting()) {
        event.preventDefault();
        created.hide();
      }
    });
    created.on("closed", () => {
      if (win === created) win = null;
      deps.onStateChange();
    });
    return created;
  }

  function defaultSpot(): { x: number; y: number } {
    const area = deps.workAreas()[0] ?? { x: 0, y: 0, width: 1280, height: 720 };
    return {
      x: area.x + area.width - WIDGET_WIDTH - EDGE_GAP,
      y: area.y + area.height - WIDGET_HEIGHT - EDGE_GAP,
    };
  }

  function isOnAnyScreen(bounds: Rect): boolean {
    return deps.workAreas().some((area) => {
      const w = Math.min(bounds.x + bounds.width, area.x + area.width) - Math.max(bounds.x, area.x);
      const h = Math.min(bounds.y + bounds.height, area.y + area.height) - Math.max(bounds.y, area.y);
      return w >= MIN_VISIBLE_PX && h >= MIN_VISIBLE_PX;
    });
  }

  function place(window: WidgetWindowLike): void {
    if (!placed || !isOnAnyScreen(window.getBounds())) {
      const spot = defaultSpot();
      window.setPosition(spot.x, spot.y);
      placed = true;
    }
  }

  function isMinimized(): boolean {
    const w = live();
    return !!w && w.isMinimized();
  }

  function isShown(): boolean {
    const w = live();
    return !!w && w.isVisible() && !w.isMinimized();
  }

  function open(options: { focus?: boolean } = {}): void {
    const focus = options.focus ?? true;
    const window = ensureWindow();

    if (window.isMinimized()) {
      window.restore();
      if (focus) window.focus();
      return;
    }
    place(window);
    if (window.isVisible()) {
      if (focus) window.focus();
      return;
    }
    if (focus) window.show();
    else window.showInactive();
    const b = window.getBounds();
    deps.log?.(`[widget] shown at x=${b.x} y=${b.y} (${b.width}x${b.height})`);
  }

  return {
    open,
    hide(): void {
      live()?.hide();
    },
    minimize(): void {
      const w = live();
      if (w && w.isVisible() && !w.isMinimized()) w.minimize();
    },
    toggle(): boolean {
      if (isShown()) {
        live()?.hide();
        return false;
      }
      open({ focus: true });   // hidden OR minimized -> bring it back
      return true;
    },
    isShown,
    isMinimized,
  };
}

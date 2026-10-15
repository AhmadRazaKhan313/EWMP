/**
 * The floating widget's window lifecycle -- the bug was that it vanished and
 * never came back: no taskbar button (skipTaskbar), and "minimize" was really
 * hide(). Tested against a fake window that behaves like Electron's.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  createWidgetWindowManager,
  WIDGET_HEIGHT,
  WIDGET_WIDTH,
  type Rect,
  type WidgetWindowLike,
} from "../widgetWindow";

class FakeWindow implements WidgetWindowLike {
  destroyed = false;
  visible = false;
  minimized = false;
  bounds: Rect = { x: 0, y: 0, width: WIDGET_WIDTH, height: WIDGET_HEIGHT };
  calls: string[] = [];
  private handlers = new Map<string, Array<(...args: unknown[]) => void>>();

  isDestroyed() { return this.destroyed; }
  isVisible() { return this.visible && !this.destroyed; }
  isMinimized() { return this.minimized; }
  show() { this.calls.push("show"); this.visible = true; this.minimized = false; this.emit("show"); }
  showInactive() { this.calls.push("showInactive"); this.visible = true; this.emit("show"); }
  hide() { this.calls.push("hide"); this.visible = false; this.emit("hide"); }
  minimize() { this.calls.push("minimize"); this.minimized = true; this.emit("minimize"); }
  restore() { this.calls.push("restore"); this.minimized = false; this.visible = true; this.emit("restore"); }
  focus() { this.calls.push("focus"); }
  setPosition(x: number, y: number) { this.calls.push(`setPosition(${x},${y})`); this.bounds = { ...this.bounds, x, y }; }
  getBounds() { return this.bounds; }
  on(event: string, listener: (...args: unknown[]) => void) {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), listener]);
    return this;
  }
  emit(event: string, ...args: unknown[]) { (this.handlers.get(event) ?? []).forEach((h) => h(...args)); }
  /** What the OS does when the user hits the X / Alt+F4. */
  userClose() {
    let prevented = false;
    this.emit("close", { preventDefault: () => { prevented = true; } });
    if (!prevented) { this.destroyed = true; this.emit("closed"); }
    return prevented;
  }
}

const SCREEN: Rect = { x: 0, y: 0, width: 1920, height: 1040 };   // work area (taskbar excluded)

function setup(opts: { quitting?: boolean; areas?: Rect[] } = {}) {
  const created: FakeWindow[] = [];
  const onStateChange = vi.fn();
  const state = { quitting: opts.quitting ?? false, areas: opts.areas ?? [SCREEN] };
  const manager = createWidgetWindowManager({
    create: () => { const w = new FakeWindow(); created.push(w); return w; },
    workAreas: () => state.areas,
    isQuitting: () => state.quitting,
    onStateChange,
  });
  return { manager, created, onStateChange, state };
}

describe("widget window lifecycle", () => {
  let t: ReturnType<typeof setup>;
  beforeEach(() => { t = setup(); });

  it("creates ONE window and reuses it however often it is opened, hidden or toggled", () => {
    t.manager.open({ focus: false });
    t.manager.hide();
    t.manager.open();
    t.manager.toggle();
    t.manager.toggle();
    t.manager.minimize();
    t.manager.open();
    t.manager.open({ focus: false });
    expect(t.created).toHaveLength(1);
  });

  it("appears bottom-right at startup WITHOUT stealing focus", () => {
    t.manager.open({ focus: false });
    const w = t.created[0]!;
    expect(w.calls).toContain(`setPosition(${SCREEN.width - WIDGET_WIDTH - 2},${SCREEN.height - WIDGET_HEIGHT - 2})`);
    expect(w.calls).toContain("showInactive");
    expect(w.calls).not.toContain("focus");
    expect(t.manager.isShown()).toBe(true);
  });

  describe("minimize", () => {
    it("is a REAL minimize (the window stays alive and keeps its taskbar button)", () => {
      t.manager.open({ focus: false });
      t.manager.minimize();
      const w = t.created[0]!;
      expect(w.calls).toContain("minimize");
      expect(w.calls).not.toContain("hide");        // the old behaviour
      expect(t.manager.isMinimized()).toBe(true);
      expect(t.manager.isShown()).toBe(false);
    });

    it("restoring (taskbar click -> restore, or open) brings the same window back", () => {
      t.manager.open({ focus: false });
      t.manager.minimize();
      t.manager.open();                              // e.g. launching the app again
      const w = t.created[0]!;
      expect(w.calls).toContain("restore");
      expect(t.manager.isShown()).toBe(true);
      expect(t.created).toHaveLength(1);
    });

    it("a restore done by the OS (taskbar) is noticed too", () => {
      t.manager.open({ focus: false });
      t.manager.minimize();
      t.onStateChange.mockClear();
      t.created[0]!.restore();                       // what clicking the taskbar button does
      expect(t.manager.isShown()).toBe(true);
      expect(t.onStateChange).toHaveBeenCalled();    // tray label refreshed
    });

    it("minimizing something that isn't showing does nothing", () => {
      t.manager.minimize();                           // never opened
      expect(t.created).toHaveLength(0);
      t.manager.open({ focus: false }); t.manager.hide();
      t.manager.minimize();
      expect(t.created[0]!.calls).not.toContain("minimize");
    });

    it("the tray item restores a minimized widget instead of hiding it", () => {
      t.manager.open({ focus: false });
      t.manager.minimize();
      expect(t.manager.toggle()).toBe(true);
      expect(t.manager.isShown()).toBe(true);
      expect(t.created[0]!.calls).not.toContain("hide");
    });
  });

  describe("close / hide", () => {
    it("the X (and Alt+F4) HIDES to the tray -- the window is kept, not destroyed", () => {
      t.manager.open({ focus: false });
      const prevented = t.created[0]!.userClose();
      expect(prevented).toBe(true);
      expect(t.created[0]!.destroyed).toBe(false);
      expect(t.manager.isShown()).toBe(false);
    });

    it("after closing, opening shows the SAME window again", () => {
      t.manager.open({ focus: false });
      t.created[0]!.userClose();
      t.manager.open();
      expect(t.created).toHaveLength(1);
      expect(t.manager.isShown()).toBe(true);
    });

    it("quitting the app really closes it", () => {
      t.manager.open({ focus: false });
      t.state.quitting = true;
      expect(t.created[0]!.userClose()).toBe(false);
      expect(t.created[0]!.destroyed).toBe(true);
    });

    it("if the window was destroyed, the next open creates exactly one fresh one", () => {
      t.manager.open({ focus: false });
      t.state.quitting = true; t.created[0]!.userClose(); t.state.quitting = false;
      t.manager.open();
      t.manager.open();
      expect(t.created).toHaveLength(2);
      expect(t.manager.isShown()).toBe(true);
    });
  });

  describe("toggle (tray menu)", () => {
    it("shown -> hidden -> shown", () => {
      t.manager.open({ focus: false });
      expect(t.manager.toggle()).toBe(false);
      expect(t.manager.toggle()).toBe(true);
      expect(t.manager.isShown()).toBe(true);
    });
    it("works before the widget was ever opened", () => {
      expect(t.manager.toggle()).toBe(true);
      expect(t.created).toHaveLength(1);
    });
  });

  describe("tray menu stays in step with the window", () => {
    it("every show / hide / minimize / restore notifies the tray", () => {
      t.manager.open({ focus: false });
      t.onStateChange.mockClear();
      t.manager.minimize();
      t.manager.open();
      t.manager.hide();
      t.manager.open();
      expect(t.onStateChange.mock.calls.length).toBeGreaterThanOrEqual(4);
    });
    it("notifies when the window goes away", () => {
      t.manager.open({ focus: false });
      t.onStateChange.mockClear();
      t.state.quitting = true; t.created[0]!.userClose();
      expect(t.onStateChange).toHaveBeenCalled();
    });
  });

  describe("position", () => {
    it("keeps where the user dragged it across hide / minimize / restore", () => {
      t.manager.open({ focus: false });
      const w = t.created[0]!;
      w.bounds = { ...w.bounds, x: 300, y: 200 };    // the user dragged it
      t.manager.hide(); t.manager.open();
      t.manager.minimize(); t.manager.open();
      expect(w.bounds.x).toBe(300);
      expect(w.bounds.y).toBe(200);
    });

    it("moves it back on screen if its display was unplugged", () => {
      const second: Rect = { x: 1920, y: 0, width: 1920, height: 1040 };
      const s = setup({ areas: [SCREEN, second] });
      s.manager.open({ focus: false });
      const w = s.created[0]!;
      w.bounds = { ...w.bounds, x: 2400, y: 300 };   // dragged onto the 2nd monitor
      s.manager.hide();
      s.state.areas = [SCREEN];                       // ...which is then unplugged
      s.manager.open();
      expect(w.bounds.x).toBe(SCREEN.width - WIDGET_WIDTH - 2);
      expect(w.bounds.y).toBe(SCREEN.height - WIDGET_HEIGHT - 2);
    });
  });
});

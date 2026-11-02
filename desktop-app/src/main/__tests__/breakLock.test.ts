import { describe, it, expect, vi } from "vitest";
import { BREAK_LOCK_CHANNEL, createBreakLockController, registerBreakLockIpc } from "../breakLock";

function fakeWindow() {
  const handlers: Partial<Record<string, () => void>> = {};
  return {
    handlers,
    destroyed: false,
    isDestroyed() { return this.destroyed; },
    show: vi.fn(), focus: vi.fn(), restore: vi.fn(), isMinimized: vi.fn(() => false),
    setFullScreen: vi.fn(), setAlwaysOnTop: vi.fn(), setClosable: vi.fn(), setMinimizable: vi.fn(),
    on: vi.fn((e: string, l: () => void) => { handlers[e] = l; }),
    removeListener: vi.fn((e: string) => { delete handlers[e]; }),
  };
}

describe("break lock window controller", () => {
  it("covers the screen, blocks close/minimise, hides the widget", () => {
    const win = fakeWindow();
    const widget = { isShown: () => true, hide: vi.fn(), open: vi.fn() };
    const c = createBreakLockController({ getWindow: () => win as never, widget });
    c.setLocked(true);
    expect(c.isLocked()).toBe(true);
    expect(win.setFullScreen).toHaveBeenCalledWith(true);
    expect(win.setAlwaysOnTop).toHaveBeenCalledWith(true, "screen-saver");
    expect(win.setClosable).toHaveBeenCalledWith(false);
    expect(win.setMinimizable).toHaveBeenCalledWith(false);
    expect(widget.hide).toHaveBeenCalled();
  });

  it("takes focus back when the window loses it and un-minimises", () => {
    const win = fakeWindow();
    const c = createBreakLockController({ getWindow: () => win as never });
    c.setLocked(true);
    win.focus.mockClear();
    win.handlers.blur?.();
    win.handlers.minimize?.();
    expect(win.focus).toHaveBeenCalledTimes(1);
    expect(win.restore).toHaveBeenCalledTimes(1);
  });

  it("unlocking restores the window and the widget, and is idempotent", () => {
    const win = fakeWindow();
    const widget = { isShown: () => true, hide: vi.fn(), open: vi.fn() };
    const c = createBreakLockController({ getWindow: () => win as never, widget });
    c.setLocked(true);
    c.setLocked(true);
    expect(win.setFullScreen).toHaveBeenCalledTimes(1);
    c.setLocked(false);
    expect(win.setFullScreen).toHaveBeenLastCalledWith(false);
    expect(win.setAlwaysOnTop).toHaveBeenLastCalledWith(false);
    expect(win.setClosable).toHaveBeenLastCalledWith(true);
    expect(win.removeListener).toHaveBeenCalledTimes(2);
    expect(widget.open).toHaveBeenCalledWith({ focus: false });
    expect(c.isLocked()).toBe(false);
  });

  it("does not reopen a widget that was not showing", () => {
    const win = fakeWindow();
    const widget = { isShown: () => false, hide: vi.fn(), open: vi.fn() };
    const c = createBreakLockController({ getWindow: () => win as never, widget });
    c.setLocked(true); c.setLocked(false);
    expect(widget.hide).not.toHaveBeenCalled();
    expect(widget.open).not.toHaveBeenCalled();
  });

  it("stays unlocked when there is no window", () => {
    const c = createBreakLockController({ getWindow: () => null });
    c.setLocked(true);
    expect(c.isLocked()).toBe(false);
  });

  it("is reachable over the IPC channel", () => {
    const win = fakeWindow();
    const c = createBreakLockController({ getWindow: () => win as never });
    let fn: (e: unknown, l: boolean) => void = () => {};
    registerBreakLockIpc({ handle: (ch, f) => { expect(ch).toBe(BREAK_LOCK_CHANNEL); fn = f; } }, c);
    fn({}, true);
    expect(c.isLocked()).toBe(true);
  });
});

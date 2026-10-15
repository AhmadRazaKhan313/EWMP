import { describe, it, expect, vi } from "vitest";
import { relayToOtherWindows, type BroadcastTarget } from "../attendanceBroadcast";

const target = (id: number, destroyed = false): BroadcastTarget & { send: ReturnType<typeof vi.fn> } => ({
  id, isDestroyed: () => destroyed, send: vi.fn(),
});

describe("relayToOtherWindows (Desktop App <-> Widget sync)", () => {
  it("tells every window except the one that made the change", () => {
    const main = target(1), widget = target(2), other = target(3);
    const sent = relayToOtherWindows([main, widget, other], 2, "attendance:changed");
    expect(sent).toBe(2);
    expect(main.send).toHaveBeenCalledWith("attendance:changed");
    expect(other.send).toHaveBeenCalledWith("attendance:changed");
    expect(widget.send).not.toHaveBeenCalled();          // it already has the new state
  });

  it("skips windows that are gone", () => {
    const live = target(1), dead = target(2, true);
    expect(relayToOtherWindows([live, dead], 9, "x")).toBe(1);
    expect(dead.send).not.toHaveBeenCalled();
  });

  it("does nothing when there is no other window", () => {
    expect(relayToOtherWindows([target(1)], 1, "x")).toBe(0);
    expect(relayToOtherWindows([], 1, "x")).toBe(0);
  });
});

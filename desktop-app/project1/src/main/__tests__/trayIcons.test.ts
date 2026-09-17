import { describe, it, expect, vi } from "vitest";

vi.mock("electron", () => ({
  nativeImage: {
    createFromDataURL: (dataUrl: string): { __dataUrl: string; __representations: unknown[]; addRepresentation: (rep: unknown) => void } => ({
      __dataUrl: dataUrl,
      __representations: [] as unknown[],
      addRepresentation(rep: unknown): void {
        this.__representations.push(rep);
      },
    }),
  },
}));

import { getTrayIcon } from "../trayIcons";

describe("getTrayIcon", () => {
  it("returns a distinct icon per status", () => {
    const idle = getTrayIcon("idle") as unknown as { __dataUrl: string };
    const active = getTrayIcon("active") as unknown as { __dataUrl: string };
    const onBreak = getTrayIcon("on_break") as unknown as { __dataUrl: string };

    expect(idle.__dataUrl).toMatch(/^data:image\/png;base64,/);
    expect(active.__dataUrl).toMatch(/^data:image\/png;base64,/);
    expect(onBreak.__dataUrl).toMatch(/^data:image\/png;base64,/);

    // All three must actually differ -- a copy/paste bug reusing the
    // same base64 constant for two statuses would make the tray icon
    // silently stop reflecting state changes.
    const urls = new Set([idle.__dataUrl, active.__dataUrl, onBreak.__dataUrl]);
    expect(urls.size).toBe(3);
  });

  it("adds a @2x representation for HiDPI displays", () => {
    const icon = getTrayIcon("active") as unknown as { __representations: { scaleFactor: number }[] };
    expect(icon.__representations).toHaveLength(1);
    expect(icon.__representations[0]?.scaleFactor).toBe(2);
  });

  it("returns the same cached instance on repeated calls (icons are built once)", () => {
    expect(getTrayIcon("idle")).toBe(getTrayIcon("idle"));
  });
});

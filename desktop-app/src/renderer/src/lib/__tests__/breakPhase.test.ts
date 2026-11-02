import { describe, it, expect } from "vitest";
import { deriveBreakView, mmss } from "../breakPhase";
import type { BreakInfo } from "../../services/breakLockService";

const T0 = Date.parse("2026-11-02T13:00:00Z");
const info = (over: Partial<BreakInfo> = {}): BreakInfo => ({
  server_time: "2026-11-02T12:00:00Z", has_break: true, phase: "upcoming", locked: false,
  start: "2026-11-02T13:00:00Z", end: "2026-11-02T14:00:00Z", duration_minutes: 60, request: null, ...over,
});
const at = (offsetSeconds: number, i = info(), clockOffsetMs = 0) => deriveBreakView(i, clockOffsetMs, T0 + offsetSeconds * 1000);

describe("deriveBreakView", () => {
  it("no break", () => {
    expect(deriveBreakView(undefined, 0, T0).phase).toBe("none");
    expect(deriveBreakView(info({ has_break: false }), 0, T0).locked).toBe(false);
  });
  it("walks upcoming → warning → active → over", () => {
    expect(at(-3600).phase).toBe("upcoming");
    expect(at(-300).phase).toBe("warning");
    expect(at(-299).secondsToStart).toBe(299);
    expect(at(0).phase).toBe("active");
    expect(at(0).locked).toBe(true);
    expect(at(1800).secondsToEnd).toBe(1800);
    expect(at(3600).phase).toBe("over");
    expect(at(3600).locked).toBe(false);
  });
  it("uses the server's clock when the PC clock is wrong", () => {
    // PC is 10 minutes slow: at PC time 12:50 the server says 13:00 → locked
    expect(at(-600, info(), 600_000).locked).toBe(true);
  });
  it("an approved unlock keeps the screen open for the rest of the break", () => {
    const i = info({ unlocked_by_admin: true, request: { id: "r", status: "approved", reason: null } });
    expect(at(600, i).phase).toBe("active");
    expect(at(600, i).locked).toBe(false);
  });
  it("a denied or pending request stays locked", () => {
    for (const status of ["denied", "pending"] as const) {
      expect(at(600, info({ request: { id: "r", status, reason: null } })).locked).toBe(true);
    }
  });
});

describe("mmss", () => {
  it("formats", () => { expect(mmss(0)).toBe("00:00"); expect(mmss(3599)).toBe("59:59"); expect(mmss(3600)).toBe("60:00"); });
});

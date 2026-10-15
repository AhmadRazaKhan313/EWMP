/**
 * The website's shared attendance view: one query, one set of refresh rules and
 * one piece of arithmetic for every component, so they can never disagree.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));
vi.mock("../api-client", () => ({ default: { get: getMock } }));

import {
  ACTIVE_SESSION_KEY,
  ATTENDANCE_QUERY_OPTIONS,
  ATTENDANCE_SYNC_INTERVAL_MS,
  fetchActiveSession,
  sessionClock,
  type ActiveSession,
} from "../attendanceSession.service";

const NOW = new Date("2026-10-06T12:00:00Z").getTime();
const iso = (msBeforeNow: number): string => new Date(NOW - msBeforeNow).toISOString();
const session = (over: Partial<ActiveSession> = {}): ActiveSession => ({
  id: "s1", started_at: iso(2 * 3600_000), status: "active", total_break_seconds: 0,
  current_break_started_at: null, clock_offset_ms: 0, ...over,
});

describe("sessionClock", () => {
  it("is all zeros when nobody is checked in", () => {
    expect(sessionClock(null, NOW)).toEqual({ isCheckedIn: false, isOnBreak: false, workedSeconds: 0, breakSeconds: 0 });
    expect(sessionClock(undefined, NOW).isCheckedIn).toBe(false);
    expect(sessionClock(session({ status: "ended" }), NOW).isCheckedIn).toBe(false);
  });

  it("working: worked time = time since check-in", () => {
    const c = sessionClock(session(), NOW);
    expect(c).toMatchObject({ isCheckedIn: true, isOnBreak: false, workedSeconds: 7200, breakSeconds: 0 });
  });

  it("finished breaks come off the worked time and are reported as break time", () => {
    const c = sessionClock(session({ total_break_seconds: 45 * 60 + 12 }), NOW);
    expect(c.workedSeconds).toBe(7200 - 2712);
    expect(c.breakSeconds).toBe(2712);
  });

  it("on a break: the worked time PAUSES and the break time keeps counting", () => {
    const s = session({ status: "on_break", total_break_seconds: 600, current_break_started_at: iso(300_000) });
    const at = (extraMs: number) => sessionClock(s, NOW + extraMs);
    expect(at(0)).toMatchObject({ isOnBreak: true, workedSeconds: 7200 - 900, breakSeconds: 900 });
    expect(at(60_000).workedSeconds).toBe(at(0).workedSeconds);            // frozen
    expect(at(60_000).breakSeconds).toBe(at(0).breakSeconds + 60);         // counting
  });

  it("when the break ends the worked time resumes from where it stopped", () => {
    const during = sessionClock(session({ status: "on_break", current_break_started_at: iso(300_000) }), NOW);
    const after = sessionClock(session({ total_break_seconds: 300 }), NOW);   // same break, now finished
    expect(after.workedSeconds).toBe(during.workedSeconds);
    expect(after.breakSeconds).toBe(during.breakSeconds);
  });

  it("falls back to whole minutes if an older server sends no seconds", () => {
    const c = sessionClock(session({ total_break_seconds: undefined, total_break_minutes: 10 }), NOW);
    expect(c.breakSeconds).toBe(600);
  });

  it("counts from the SERVER's clock: a device whose clock is 10 minutes fast shows the same time", () => {
    const honest = sessionClock(session({ clock_offset_ms: 0 }), NOW);
    // This device's clock reads 10 minutes ahead; the measured offset undoes it.
    const fastDevice = sessionClock(session({ clock_offset_ms: -600_000 }), NOW + 600_000);
    expect(fastDevice.workedSeconds).toBe(honest.workedSeconds);
  });
});

describe("fetchActiveSession", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.useFakeTimers(); vi.setSystemTime(NOW); });
  afterEach(() => vi.useRealTimers());

  it("asks for the caller's active session", async () => {
    getMock.mockResolvedValue({ data: null });
    expect(await fetchActiveSession()).toBeNull();
    expect(getMock).toHaveBeenCalledWith("/work-sessions/me/active");
  });

  it("measures how far this device's clock is from the server's, at the moment the answer arrives", async () => {
    getMock.mockResolvedValue({ data: { id: "s1", started_at: iso(3600_000), status: "active", server_time: new Date(NOW - 420_000).toISOString() } });
    const s = await fetchActiveSession();
    expect(s?.clock_offset_ms).toBe(-420_000);                 // this device is 7 minutes ahead
  });

  it("assumes no offset when an older server sends no server_time", async () => {
    getMock.mockResolvedValue({ data: { id: "s1", started_at: iso(3600_000), status: "active" } });
    expect((await fetchActiveSession())?.clock_offset_ms).toBe(0);
  });
});

describe("refresh rules shared by every attendance reader", () => {
  it("poll within a few seconds, and refetch on focus and when the network returns", () => {
    expect(ATTENDANCE_SYNC_INTERVAL_MS).toBeLessThanOrEqual(5_000);
    expect(ATTENDANCE_QUERY_OPTIONS).toMatchObject({
      refetchInterval: ATTENDANCE_SYNC_INTERVAL_MS,
      refetchOnWindowFocus: true,    // the app-wide default is false
      refetchOnReconnect: true,
      staleTime: 0,                  // the app-wide default is one minute
    });
  });
  it("every reader uses the same cache key", () => {
    expect(ACTIVE_SESSION_KEY).toEqual(["work-session", "active"]);
  });
});

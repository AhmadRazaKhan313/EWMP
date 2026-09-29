import { describe, it, expect, vi, beforeEach } from "vitest";
import { useTimerStore, workSessionService, formatElapsed, type WorkSession } from "../timerStore";

vi.mock("@shared/api-client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

function session(overrides: Partial<WorkSession> = {}): WorkSession {
  return {
    id: "s1", employee_id: "e1", started_at: new Date().toISOString(), ended_at: null,
    status: "active", total_minutes: null, total_break_minutes: 0, total_break_seconds: 0, current_break_started_at: null,
    ...overrides,
  };
}

function reset(): void {
  useTimerStore.setState({
    status: "loading", sessionId: null, startedAt: null,
    elapsedSeconds: 0, breakSeconds: 0, completedBreakSeconds: 0, breakStartedAt: null,
    error: null, breakTypes: [], todaysBreaks: [],
  });
}

describe("formatElapsed", () => {
  it("formats seconds as HH:MM:SS", () => {
    expect(formatElapsed(0)).toBe("00:00:00");
    expect(formatElapsed(65)).toBe("00:01:05");
    expect(formatElapsed(3661)).toBe("01:01:01");
  });
});

describe("timerStore.init", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("sets status=idle when no active session exists on the server", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
    await useTimerStore.getState().init();
    expect(useTimerStore.getState().status).toBe("idle");
  });

  it("restores an in-progress session, re-deriving elapsed time from server started_at", async () => {
    const startedAt = new Date(Date.now() - 90_000).toISOString(); // 90s ago
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(session({ started_at: startedAt }));
    await useTimerStore.getState().init();
    const state = useTimerStore.getState();
    expect(state.status).toBe("active");
    expect(state.elapsedSeconds).toBeGreaterThanOrEqual(89);
  });

  it("restores a session that's mid-break with the timer already paused and the break timer already running", async () => {
    const startedAt = new Date(Date.now() - 600_000).toISOString(); // checked in 10m ago
    const breakStartedAt = new Date(Date.now() - 120_000).toISOString(); // on break for 2m
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(
      session({ status: "on_break", started_at: startedAt, current_break_started_at: breakStartedAt }),
    );
    await useTimerStore.getState().init();
    const state = useTimerStore.getState();
    expect(state.status).toBe("on_break");
    expect(state.breakSeconds).toBeGreaterThanOrEqual(119);
    // 10m since check-in minus ~2m of ongoing break ≈ 8m worked
    expect(state.elapsedSeconds).toBeGreaterThanOrEqual(475);
    expect(state.elapsedSeconds).toBeLessThan(490);
  });
});

describe("timerStore.checkIn / checkOut", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("checkIn sets status=active with a fresh session", async () => {
    vi.spyOn(workSessionService, "start").mockResolvedValue(session());
    await useTimerStore.getState().checkIn();
    expect(useTimerStore.getState().status).toBe("active");
    expect(useTimerStore.getState().sessionId).toBe("s1");
  });

  it("checkOut resets to idle and clears break bookkeeping", async () => {
    useTimerStore.setState({
      status: "active", sessionId: "s1", startedAt: Date.now(),
      elapsedSeconds: 10, breakSeconds: 0, completedBreakSeconds: 300, breakStartedAt: null,
    });
    vi.spyOn(workSessionService, "end").mockResolvedValue(
      session({ started_at: "", ended_at: new Date().toISOString(), status: "ended", total_minutes: 5 }),
    );
    await useTimerStore.getState().checkOut();
    const state = useTimerStore.getState();
    expect(state.status).toBe("idle");
    expect(state.sessionId).toBeNull();
    expect(state.completedBreakSeconds).toBe(0);
    expect(state.breakStartedAt).toBeNull();
  });

  it("surfaces an error on check-in failure without crashing", async () => {
    vi.spyOn(workSessionService, "start").mockRejectedValue(new Error("network down"));
    await useTimerStore.getState().checkIn();
    expect(useTimerStore.getState().error).toBe("network down");
  });

  // Regression test for a real bug report: a brand-new employee under a
  // brand-new organization checked in and saw an unhelpful generic
  // "network issue" message. Two distinct causes were found and are
  // covered here — see describeTimerError's doc comment in timerStore.ts.
  it("shows a specific, actionable message when the request never reaches the server", async () => {
    // Shaped like a real Axios error for a connection that never got a
    // response at all (DNS failure, connection refused, CORS block,
    // timeout) — `response` is an own key with value undefined, which is
    // exactly how Axios constructs this, and is NOT the same as a plain
    // Error with no `response` key at all (covered by the test above).
    const networkError = Object.assign(new Error("Network Error"), { response: undefined });
    vi.spyOn(workSessionService, "start").mockRejectedValue(networkError);
    await useTimerStore.getState().checkIn();
    expect(useTimerStore.getState().error).toMatch(/can't reach the server/i);
  });

  it("shows actionable guidance when the account has no linked employee profile", async () => {
    // Shape of backend/app/core/exceptions.py's EmployeeProfileNotLinkedError
    // once it passes through the exception_handlers.py JSON envelope.
    const linkError = Object.assign(new Error("Not Found"), {
      response: { status: 404, data: { error: "EMPLOYEE_PROFILE_NOT_LINKED", message: "Your account isn't linked to an employee profile yet." } },
    });
    vi.spyOn(workSessionService, "start").mockRejectedValue(linkError);
    await useTimerStore.getState().checkIn();
    expect(useTimerStore.getState().error).toMatch(/ask your hr admin/i);
  });

  it("still shows the backend's own message for anything else, e.g. a 409", async () => {
    const conflictError = Object.assign(new Error("Conflict"), {
      response: { status: 409, data: { message: "Today's session has already ended. Start a new one from Break instead." } },
    });
    vi.spyOn(workSessionService, "start").mockRejectedValue(conflictError);
    await useTimerStore.getState().checkIn();
    expect(useTimerStore.getState().error).toBe("Today's session has already ended. Start a new one from Break instead.");
  });
});

describe("timerStore._tick — the pause/resume bug fix", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("advances elapsedSeconds while active, with no break time to subtract", () => {
    useTimerStore.setState({ status: "active", startedAt: Date.now() - 5000, completedBreakSeconds: 0, breakStartedAt: null });
    useTimerStore.getState()._tick();
    expect(useTimerStore.getState().elapsedSeconds).toBeGreaterThanOrEqual(4);
  });

  it("does nothing while idle", () => {
    useTimerStore.setState({ status: "idle", startedAt: Date.now() - 5000, elapsedSeconds: 0 });
    useTimerStore.getState()._tick();
    expect(useTimerStore.getState().elapsedSeconds).toBe(0);
  });

  it("BUG FIX: elapsedSeconds (the worked timer) does NOT advance while on_break — it freezes", () => {
    // Checked in 10s ago, break started just now (0 completed breaks yet).
    useTimerStore.setState({
      status: "on_break", startedAt: Date.now() - 10_000,
      completedBreakSeconds: 0, breakStartedAt: Date.now(), elapsedSeconds: 10,
    });
    useTimerStore.getState()._tick();
    // secondsSinceCheckIn (~10) minus breakSeconds (~0) minus completed (0) ≈ 10, i.e. unchanged —
    // it must NOT have kept climbing past 10 the way "time since check-in" would.
    expect(useTimerStore.getState().elapsedSeconds).toBeLessThanOrEqual(10);
  });

  it("BUG FIX: breakSeconds climbs while on_break, independently of elapsedSeconds", () => {
    useTimerStore.setState({
      status: "on_break", startedAt: Date.now() - 60_000,
      completedBreakSeconds: 0, breakStartedAt: Date.now() - 5000,
    });
    useTimerStore.getState()._tick();
    expect(useTimerStore.getState().breakSeconds).toBeGreaterThanOrEqual(4);
  });

  it("BUG FIX: resuming from break continues elapsedSeconds from where it paused, not from 0 and not from total-since-checkin", () => {
    // Checked in 100s ago; already had 20s of completed break before this one;
    // just resumed (breakStartedAt cleared) — worked so far should be ~80s.
    useTimerStore.setState({
      status: "active", startedAt: Date.now() - 100_000,
      completedBreakSeconds: 20, breakStartedAt: null,
    });
    useTimerStore.getState()._tick();
    const elapsed = useTimerStore.getState().elapsedSeconds;
    expect(elapsed).toBeGreaterThanOrEqual(79);
    expect(elapsed).toBeLessThanOrEqual(81);
  });

  it("BUG FIX: total break time is subtracted from worked time — working hours net of breaks", () => {
    // 10 minutes since check-in, 3 minutes of that were a (now-completed) break.
    useTimerStore.setState({
      status: "active", startedAt: Date.now() - 600_000,
      completedBreakSeconds: 180, breakStartedAt: null,
    });
    useTimerStore.getState()._tick();
    const elapsed = useTimerStore.getState().elapsedSeconds;
    // ~600s - 180s = ~420s worked
    expect(elapsed).toBeGreaterThanOrEqual(415);
    expect(elapsed).toBeLessThanOrEqual(422);
  });
});

describe("timerStore.startBreak / endBreak", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("BUG FIX: a sub-minute break (total_break_minutes=0, the lossy backend value) still correctly pauses/subtracts via total_break_seconds", async () => {
    // Reproduces the exact reported bug: 1 min worked, then a break that
    // the backend's floor-divided total_break_minutes would report as 0
    // (e.g. a 45-second break) — before the fix, elapsedSeconds would
    // NOT drop by the break's real duration, so resuming showed one
    // extra minute of "worked" time that was actually break time.
    useTimerStore.setState({ status: "on_break", sessionId: "s1", startedAt: Date.now() - 105_000 }); // 1min45s since check-in
    vi.spyOn(workSessionService, "endBreak").mockResolvedValue(
      // Backend's lossy total_break_minutes says 0 — but the real break
      // was 45 real seconds (total_break_seconds is exact). started_at
      // must match the store's local anchor above — deriveTimerFields()
      // computes from the SERVER's started_at, not the store's stale copy.
      session({
        status: "active", started_at: new Date(Date.now() - 105_000).toISOString(),
        total_break_minutes: 0, total_break_seconds: 45, current_break_started_at: null,
      }),
    );

    await useTimerStore.getState().endBreak();

    const state = useTimerStore.getState();
    // ~105s since check-in minus the 45s break = ~60s worked (1 min),
    // NOT ~105s (which is what the old total_break_minutes*60=0 bug
    // would have produced — no subtraction at all).
    expect(state.elapsedSeconds).toBeGreaterThanOrEqual(58);
    expect(state.elapsedSeconds).toBeLessThanOrEqual(62);
  });

  it("startBreak flips status to on_break and adopts the server's break bookkeeping", async () => {
    useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now() - 1000, elapsedSeconds: 1 });
    const breakStartedAt = new Date().toISOString();
    vi.spyOn(workSessionService, "startBreak").mockResolvedValue(
      session({ status: "on_break", current_break_started_at: breakStartedAt }),
    );

    await useTimerStore.getState().startBreak();

    const state = useTimerStore.getState();
    expect(state.status).toBe("on_break");
    expect(state.sessionId).toBe("s1"); // same session — break pauses, doesn't end
    expect(state.breakStartedAt).toBeCloseTo(new Date(breakStartedAt).getTime(), -1);
  });

  it("passes a break_type_id through to the backend when a category is picked (Phase 5)", async () => {
    useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now(), elapsedSeconds: 0 });
    const spy = vi.spyOn(workSessionService, "startBreak").mockResolvedValue(session({ status: "on_break" }));

    await useTimerStore.getState().startBreak("bt-lunch");

    expect(spy).toHaveBeenCalledWith("s1", "bt-lunch");
  });

  it("omits the break_type_id for a plain quick pause (Phase 4 behavior unchanged)", async () => {
    useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now(), elapsedSeconds: 0 });
    const spy = vi.spyOn(workSessionService, "startBreak").mockResolvedValue(session({ status: "on_break" }));

    await useTimerStore.getState().startBreak();

    expect(spy).toHaveBeenCalledWith("s1", undefined);
  });

  it("endBreak resumes to active and clears breakStartedAt/breakSeconds", async () => {
    useTimerStore.setState({
      status: "on_break", sessionId: "s1", startedAt: Date.now() - 5000,
      elapsedSeconds: 5, breakSeconds: 30, breakStartedAt: Date.now() - 30_000,
    });
    vi.spyOn(workSessionService, "endBreak").mockResolvedValue(
      session({ status: "active", total_break_minutes: 1, total_break_seconds: 60, current_break_started_at: null }),
    );

    await useTimerStore.getState().endBreak();

    const state = useTimerStore.getState();
    expect(state.status).toBe("active");
    expect(state.breakStartedAt).toBeNull();
    expect(state.breakSeconds).toBe(0);
    expect(state.completedBreakSeconds).toBe(60); // rolled the finished break into completed
  });

  it("startBreak is a no-op with no active session", async () => {
    const spy = vi.spyOn(workSessionService, "startBreak");
    await useTimerStore.getState().startBreak(); // sessionId is null after reset()
    expect(spy).not.toHaveBeenCalled();
  });

  it("surfaces an error if starting a break fails, without crashing", async () => {
    useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now(), elapsedSeconds: 0 });
    vi.spyOn(workSessionService, "startBreak").mockRejectedValue(new Error("session already ended"));

    await useTimerStore.getState().startBreak();

    expect(useTimerStore.getState().error).toBe("session already ended");
    expect(useTimerStore.getState().status).toBe("active"); // stays active, doesn't fake a break
  });
});

describe("timerStore.loadBreakTypes", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("populates breakTypes from the backend", async () => {
    vi.spyOn(workSessionService, "getBreakTypes").mockResolvedValue([
      { id: "bt1", name: "Lunch", is_paid: false, max_minutes: 60 },
    ]);
    await useTimerStore.getState().loadBreakTypes();
    expect(useTimerStore.getState().breakTypes).toEqual([{ id: "bt1", name: "Lunch", is_paid: false, max_minutes: 60 }]);
  });

  it("fails open to an empty list on an older backend / network error", async () => {
    vi.spyOn(workSessionService, "getBreakTypes").mockRejectedValue(new Error("404"));
    await useTimerStore.getState().loadBreakTypes();
    expect(useTimerStore.getState().breakTypes).toEqual([]);
  });
});

describe("timerStore.refreshBreaks", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("populates todaysBreaks for the current session", async () => {
    useTimerStore.setState({ sessionId: "s1" });
    vi.spyOn(workSessionService, "listBreaks").mockResolvedValue([
      { id: "b1", started_at: new Date().toISOString(), ended_at: null },
    ]);
    await useTimerStore.getState().refreshBreaks();
    expect(useTimerStore.getState().todaysBreaks).toHaveLength(1);
  });

  it("is a no-op with no active session", async () => {
    const spy = vi.spyOn(workSessionService, "listBreaks");
    await useTimerStore.getState().refreshBreaks(); // sessionId is null after reset()
    expect(spy).not.toHaveBeenCalled();
  });

  it("leaves stale data rather than throwing on a background-refresh failure", async () => {
    useTimerStore.setState({ sessionId: "s1", todaysBreaks: [{ id: "old", started_at: "x", ended_at: "y" }] });
    vi.spyOn(workSessionService, "listBreaks").mockRejectedValue(new Error("network blip"));
    await useTimerStore.getState().refreshBreaks();
    expect(useTimerStore.getState().todaysBreaks).toEqual([{ id: "old", started_at: "x", ended_at: "y" }]);
  });
});

describe("timerStore clears todaysBreaks across check-in/check-out cycles", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("checkIn resets todaysBreaks from a previous cycle", async () => {
    useTimerStore.setState({ todaysBreaks: [{ id: "stale", started_at: "x", ended_at: "y" }] });
    vi.spyOn(workSessionService, "start").mockResolvedValue(session());
    await useTimerStore.getState().checkIn();
    expect(useTimerStore.getState().todaysBreaks).toEqual([]);
  });

  it("checkOut clears todaysBreaks", async () => {
    useTimerStore.setState({
      status: "active", sessionId: "s1", startedAt: Date.now(),
      todaysBreaks: [{ id: "b1", started_at: "x", ended_at: "y" }],
    });
    vi.spyOn(workSessionService, "end").mockResolvedValue(
      session({ started_at: "", ended_at: new Date().toISOString(), status: "ended", total_minutes: 5 }),
    );
    await useTimerStore.getState().checkOut();
    expect(useTimerStore.getState().todaysBreaks).toEqual([]);
  });
});

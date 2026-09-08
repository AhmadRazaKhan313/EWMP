import { describe, it, expect, vi, beforeEach } from "vitest";
import { useTimerStore, workSessionService, formatElapsed } from "../timerStore";

vi.mock("@shared/api-client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

function reset(): void {
  useTimerStore.setState({
    status: "loading", sessionId: null, startedAt: null, elapsedSeconds: 0, error: null,
    breakTypes: [], todaysBreaks: [],
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
    vi.spyOn(workSessionService, "getActive").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: startedAt, ended_at: null, status: "active", total_minutes: null,
    });
    await useTimerStore.getState().init();
    const state = useTimerStore.getState();
    expect(state.status).toBe("active");
    expect(state.elapsedSeconds).toBeGreaterThanOrEqual(89);
  });
});

describe("timerStore.checkIn / checkOut", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("checkIn sets status=active with a fresh session", async () => {
    vi.spyOn(workSessionService, "start").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: new Date().toISOString(), ended_at: null, status: "active", total_minutes: null,
    });
    await useTimerStore.getState().checkIn();
    expect(useTimerStore.getState().status).toBe("active");
    expect(useTimerStore.getState().sessionId).toBe("s1");
  });

  it("checkOut resets to idle", async () => {
    useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now(), elapsedSeconds: 10 });
    vi.spyOn(workSessionService, "end").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: "", ended_at: new Date().toISOString(), status: "ended", total_minutes: 5,
    });
    await useTimerStore.getState().checkOut();
    expect(useTimerStore.getState().status).toBe("idle");
    expect(useTimerStore.getState().sessionId).toBeNull();
  });

  it("surfaces an error on check-in failure without crashing", async () => {
    vi.spyOn(workSessionService, "start").mockRejectedValue(new Error("network down"));
    await useTimerStore.getState().checkIn();
    expect(useTimerStore.getState().error).toBe("network down");
  });
});

describe("timerStore._tick", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("only advances elapsedSeconds while active", () => {
    useTimerStore.setState({ status: "idle", startedAt: Date.now() - 5000, elapsedSeconds: 0 });
    useTimerStore.getState()._tick();
    expect(useTimerStore.getState().elapsedSeconds).toBe(0); // idle -> no tick

    useTimerStore.setState({ status: "active" });
    useTimerStore.getState()._tick();
    expect(useTimerStore.getState().elapsedSeconds).toBeGreaterThanOrEqual(4);
  });

  it("also keeps advancing elapsedSeconds while on_break", () => {
    useTimerStore.setState({ status: "on_break", startedAt: Date.now() - 5000, elapsedSeconds: 0 });
    useTimerStore.getState()._tick();
    expect(useTimerStore.getState().elapsedSeconds).toBeGreaterThanOrEqual(4);
  });
});

describe("timerStore.startBreak / endBreak", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("startBreak flips status to on_break without touching sessionId/startedAt", async () => {
    useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now() - 1000, elapsedSeconds: 1 });
    vi.spyOn(workSessionService, "startBreak").mockResolvedValue({ status: "on_break" });

    await useTimerStore.getState().startBreak();

    const state = useTimerStore.getState();
    expect(state.status).toBe("on_break");
    expect(state.sessionId).toBe("s1"); // same session — break pauses, doesn't end
  });

  it("passes a break_type_id through to the backend when a category is picked (Phase 5)", async () => {
    useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now(), elapsedSeconds: 0 });
    const spy = vi.spyOn(workSessionService, "startBreak").mockResolvedValue({ status: "on_break" });

    await useTimerStore.getState().startBreak("bt-lunch");

    expect(spy).toHaveBeenCalledWith("s1", "bt-lunch");
  });

  it("omits the break_type_id for a plain quick pause (Phase 4 behavior unchanged)", async () => {
    useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now(), elapsedSeconds: 0 });
    const spy = vi.spyOn(workSessionService, "startBreak").mockResolvedValue({ status: "on_break" });

    await useTimerStore.getState().startBreak();

    expect(spy).toHaveBeenCalledWith("s1", undefined);
  });

  it("endBreak resumes to active", async () => {
    useTimerStore.setState({ status: "on_break", sessionId: "s1", startedAt: Date.now() - 5000, elapsedSeconds: 5 });
    vi.spyOn(workSessionService, "endBreak").mockResolvedValue({ status: "active" });

    await useTimerStore.getState().endBreak();

    expect(useTimerStore.getState().status).toBe("active");
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
    vi.spyOn(workSessionService, "start").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: new Date().toISOString(), ended_at: null, status: "active", total_minutes: null,
    });
    await useTimerStore.getState().checkIn();
    expect(useTimerStore.getState().todaysBreaks).toEqual([]);
  });

  it("checkOut clears todaysBreaks", async () => {
    useTimerStore.setState({
      status: "active", sessionId: "s1", startedAt: Date.now(),
      todaysBreaks: [{ id: "b1", started_at: "x", ended_at: "y" }],
    });
    vi.spyOn(workSessionService, "end").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: "", ended_at: new Date().toISOString(), status: "ended", total_minutes: 5,
    });
    await useTimerStore.getState().checkOut();
    expect(useTimerStore.getState().todaysBreaks).toEqual([]);
  });
});

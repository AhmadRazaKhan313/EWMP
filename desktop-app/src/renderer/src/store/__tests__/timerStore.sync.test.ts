/**
 * The desktop timer store as a view of the SERVER's attendance state:
 * a shared time base, protection against stale reads and double actions, and
 * telling the other windows when it changes something.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useTimerStore, workSessionService, type WorkSession } from "../timerStore";

vi.mock("@shared/api-client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

const notifyChanged = vi.fn();

function session(over: Partial<WorkSession> = {}): WorkSession {
  return {
    id: "s1", employee_id: "e1", started_at: new Date(Date.now() - 3600_000).toISOString(), ended_at: null,
    status: "active", total_minutes: null, total_break_minutes: 0, total_break_seconds: 0, current_break_started_at: null,
    ...over,
  };
}
const reset = (): void =>
  useTimerStore.setState({
    status: "loading", sessionId: null, startedAt: null, elapsedSeconds: 0, breakSeconds: 0,
    completedBreakSeconds: 0, breakStartedAt: null, error: null, busy: false, clockOffsetMs: 0,
    breakTypes: [], todaysBreaks: [],
  });

describe("timerStore — one attendance state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reset();
    (window as unknown as { ewmp: unknown }).ewmp = { attendance: { notifyChanged, onChanged: vi.fn() } };
    vi.spyOn(workSessionService, "listBreaks").mockResolvedValue([]);
    vi.spyOn(workSessionService, "getBreakTypes").mockResolvedValue([]);
  });
  afterEach(() => vi.useRealTimers());

  describe("shared time base (the server's clock)", () => {
    it("counts from the SERVER's clock even when this PC's clock is 10 minutes fast", async () => {
      const serverNow = Date.now() - 600_000;                      // this PC is 10 min ahead of the server
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(session({
        started_at: new Date(serverNow - 7200_000).toISOString(),  // checked in 2 h before "server now"
        server_time: new Date(serverNow).toISOString(),
      }));
      await useTimerStore.getState().init();
      const { elapsedSeconds, clockOffsetMs } = useTimerStore.getState();
      expect(elapsedSeconds).toBeGreaterThanOrEqual(7199);          // 2:00:00 -- NOT 2:10:00
      expect(elapsedSeconds).toBeLessThanOrEqual(7201);
      expect(clockOffsetMs).toBeLessThan(-599_000);
    });

    it("keeps using that offset on every tick", async () => {
      vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-06T12:00:00Z"));
      const serverNow = Date.now() - 600_000;
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(session({
        started_at: new Date(serverNow - 3600_000).toISOString(), server_time: new Date(serverNow).toISOString(),
      }));
      await useTimerStore.getState().init();
      vi.advanceTimersByTime(30_000);
      useTimerStore.getState()._tick();
      expect(useTimerStore.getState().elapsedSeconds).toBe(3630);   // 1 h + the 30 s that passed
    });

    it("two clients with different PC clocks show the same time for the same server state", async () => {
      vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-06T12:00:00Z"));
      const serverNow = Date.now();
      const body = session({ started_at: new Date(serverNow - 5400_000).toISOString(), server_time: new Date(serverNow).toISOString() });
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(body);
      await useTimerStore.getState().init();
      const a = useTimerStore.getState().elapsedSeconds;
      vi.setSystemTime(new Date("2026-10-06T12:07:00Z"));           // "another PC", clock 7 min fast
      reset();
      vi.spyOn(workSessionService, "getActive").mockResolvedValue({ ...body, server_time: new Date("2026-10-06T12:00:00Z").toISOString() });
      await useTimerStore.getState().init();
      expect(useTimerStore.getState().elapsedSeconds).toBe(a);
    });
  });

  describe("duplicate actions", () => {
    it("two break-start clicks send ONE request", async () => {
      useTimerStore.setState({ status: "active", sessionId: "s1" });
      let resolve!: (s: WorkSession) => void;
      const startBreak = vi.spyOn(workSessionService, "startBreak").mockReturnValue(new Promise((r) => { resolve = r; }));
      const first = useTimerStore.getState().startBreak();
      const second = useTimerStore.getState().startBreak();          // the impatient second click
      expect(useTimerStore.getState().busy).toBe(true);
      resolve(session({ status: "on_break", current_break_started_at: new Date().toISOString() }));
      await Promise.all([first, second]);
      expect(startBreak).toHaveBeenCalledTimes(1);
      expect(useTimerStore.getState().busy).toBe(false);
    });

    it("a check-out is ignored while a break request is still in flight", async () => {
      useTimerStore.setState({ status: "active", sessionId: "s1" });
      let resolve!: (s: WorkSession) => void;
      vi.spyOn(workSessionService, "startBreak").mockReturnValue(new Promise((r) => { resolve = r; }));
      const end = vi.spyOn(workSessionService, "end").mockResolvedValue(session({ status: "ended" }));
      const brk = useTimerStore.getState().startBreak();
      await useTimerStore.getState().checkOut();
      expect(end).not.toHaveBeenCalled();
      resolve(session({ status: "on_break", current_break_started_at: new Date().toISOString() }));
      await brk;
    });

    it("busy is released even when the request fails", async () => {
      useTimerStore.setState({ status: "active", sessionId: "s1" });
      vi.spyOn(workSessionService, "startBreak").mockRejectedValue({ response: { data: { message: "nope" } } });
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(session());
      await useTimerStore.getState().startBreak();
      expect(useTimerStore.getState().busy).toBe(false);
      expect(useTimerStore.getState().error).toBe("nope");
    });
  });

  describe("stale reads", () => {
    it("an older server read that lands AFTER a click cannot undo it", async () => {
      useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now() - 3600_000 });
      let slowRead!: (s: WorkSession | null) => void;
      vi.spyOn(workSessionService, "getActive").mockReturnValue(new Promise((r) => { slowRead = r; }));
      const refreshing = useTimerStore.getState().refresh();          // read starts: still "active"
      vi.spyOn(workSessionService, "startBreak").mockResolvedValue(session({ status: "on_break", current_break_started_at: new Date().toISOString() }));
      await useTimerStore.getState().startBreak();                    // user clicks Break meanwhile
      slowRead(session());                                            // ...the old read finally answers "active"
      await refreshing;
      expect(useTimerStore.getState().status).toBe("on_break");
    });

    it("a refresh does nothing while an action is in flight", async () => {
      useTimerStore.setState({ status: "active", sessionId: "s1", busy: true });
      const getActive = vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
      await useTimerStore.getState().refresh();
      expect(getActive).not.toHaveBeenCalled();
    });
  });

  describe("converging with the server", () => {
    it("a refresh brings in a break started elsewhere, then the end of it", async () => {
      useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now() - 3600_000 });
      const getActive = vi.spyOn(workSessionService, "getActive");
      getActive.mockResolvedValue(session({ status: "on_break", current_break_started_at: new Date(Date.now() - 60_000).toISOString() }));
      await useTimerStore.getState().refresh();
      expect(useTimerStore.getState().status).toBe("on_break");
      expect(useTimerStore.getState().breakSeconds).toBeGreaterThanOrEqual(59);

      getActive.mockResolvedValue(session({ total_break_seconds: 60 }));
      await useTimerStore.getState().refresh();
      expect(useTimerStore.getState().status).toBe("active");
      expect(useTimerStore.getState().breakSeconds).toBe(0);
      expect(useTimerStore.getState().completedBreakSeconds).toBe(60);
    });

    it("a refresh brings in a check-out made elsewhere", async () => {
      useTimerStore.setState({ status: "active", sessionId: "s1", startedAt: Date.now() - 3600_000, elapsedSeconds: 3600 });
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
      await useTimerStore.getState().refresh();
      expect(useTimerStore.getState().status).toBe("idle");
      expect(useTimerStore.getState().elapsedSeconds).toBe(0);
    });

    it("a failed refresh keeps what is on screen", async () => {
      useTimerStore.setState({ status: "on_break", sessionId: "s1", startedAt: Date.now() - 3600_000, elapsedSeconds: 3000 });
      vi.spyOn(workSessionService, "getActive").mockRejectedValue(new Error("Network Error"));
      await useTimerStore.getState().refresh();
      expect(useTimerStore.getState().status).toBe("on_break");
      expect(useTimerStore.getState().elapsedSeconds).toBe(3000);
    });

    it("an action that fails because the screen was out of date re-reads the server", async () => {
      useTimerStore.setState({ status: "active", sessionId: "s1" });
      vi.spyOn(workSessionService, "end").mockRejectedValue({ response: { data: { message: "This session has already ended" } } });
      const getActive = vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);   // it was checked out elsewhere
      await useTimerStore.getState().checkOut();
      await vi.waitFor(() => expect(useTimerStore.getState().status).toBe("idle"));
      expect(getActive).toHaveBeenCalled();
      expect(useTimerStore.getState().error).toBe("This session has already ended");       // message not wiped by the re-read
    });

    it("a refresh never clears an error that is on screen", async () => {
      useTimerStore.setState({ status: "idle", error: "Today's session has already ended." });
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
      await useTimerStore.getState().refresh();
      expect(useTimerStore.getState().error).toBe("Today's session has already ended.");
    });
  });

  describe("telling the other windows", () => {
    it("check-in, break on, break off and check-out each send ONE nudge", async () => {
      vi.spyOn(workSessionService, "start").mockResolvedValue(session());
      await useTimerStore.getState().checkIn();
      vi.spyOn(workSessionService, "startBreak").mockResolvedValue(session({ status: "on_break", current_break_started_at: new Date().toISOString() }));
      await useTimerStore.getState().startBreak();
      vi.spyOn(workSessionService, "endBreak").mockResolvedValue(session());
      await useTimerStore.getState().endBreak();
      vi.spyOn(workSessionService, "end").mockResolvedValue(session({ status: "ended" }));
      await useTimerStore.getState().checkOut();
      expect(notifyChanged).toHaveBeenCalledTimes(4);
    });

    it("a failed action sends no nudge", async () => {
      vi.spyOn(workSessionService, "start").mockRejectedValue({ response: { data: { message: "x" } } });
      await useTimerStore.getState().checkIn();
      expect(notifyChanged).not.toHaveBeenCalled();
    });

    it("works without the Electron bridge (tests, plain browser)", async () => {
      (window as unknown as { ewmp: unknown }).ewmp = undefined;
      vi.spyOn(workSessionService, "start").mockResolvedValue(session());
      await expect(useTimerStore.getState().checkIn()).resolves.toBeUndefined();
      expect(useTimerStore.getState().status).toBe("active");
    });
  });
});

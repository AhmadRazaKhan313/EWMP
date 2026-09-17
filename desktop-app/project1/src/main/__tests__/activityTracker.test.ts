import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const WATCHLIST = ["facebook.com", "instagram.com", "youtube.com", "tiktok.com", "x.com"];

describe("matchWatchlist", () => {
  let matchWatchlist: typeof import("../activityTracker").matchWatchlist;

  beforeEach(async () => {
    ({ matchWatchlist } = await import("../activityTracker"));
  });

  it("matches a flagged site's name in the browser window title", () => {
    const result = matchWatchlist({ title: "(3) Facebook - Google Chrome", owner: { name: "Google Chrome" } }, WATCHLIST);
    expect(result).not.toBeNull();
    expect(result?.matched_term).toBe("facebook.com");
    expect(result?.alert_type).toBe("flagged_browsing");
  });

  it("is case-insensitive", () => {
    const result = matchWatchlist({ title: "INSTAGRAM — Mozilla Firefox", owner: { name: "firefox" } }, WATCHLIST);
    expect(result?.matched_term).toBe("instagram.com");
  });

  it("matches a standalone flagged app by its process/owner name, not just the title", () => {
    const result = matchWatchlist({ title: "Untitled - Now Playing", owner: { name: "TikTok" } }, WATCHLIST);
    expect(result?.alert_type).toBe("flagged_app_usage");
  });

  it("classifies as flagged_browsing when the hit is in the title but the owner is a generic browser", () => {
    const result = matchWatchlist({ title: "YouTube - Home", owner: { name: "msedge" } }, WATCHLIST);
    expect(result?.alert_type).toBe("flagged_browsing");
  });

  it("returns null for an unrelated window", () => {
    const result = matchWatchlist({ title: "Quarterly Report.docx - Word", owner: { name: "WINWORD" } }, WATCHLIST);
    expect(result).toBeNull();
  });

  it("skips labels under 3 characters to avoid noisy false positives (e.g. x.com -> 'x')", () => {
    // "Excel" contains "x" — must NOT match on the "x.com" watchlist entry.
    const result = matchWatchlist({ title: "Budget.xlsx - Excel", owner: { name: "EXCEL" } }, WATCHLIST);
    expect(result).toBeNull();
  });

  it("handles a watchlist entry with no dot gracefully", () => {
    const result = matchWatchlist({ title: "Netflix", owner: { name: "Netflix" } }, ["netflix"]);
    expect(result?.matched_term).toBe("netflix");
  });

  it("returns null when the watchlist is empty", () => {
    const result = matchWatchlist({ title: "Facebook", owner: { name: "Chrome" } }, []);
    expect(result).toBeNull();
  });
});

describe("activity tracking lifecycle", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.doUnmock("get-windows");
  });

  it("does nothing while the watchlist is empty, even once started", async () => {
    vi.doMock("get-windows", () => ({
      activeWindow: vi.fn().mockResolvedValue({ title: "Facebook", owner: { name: "Chrome" } }),
    }));
    const tracker = await import("../activityTracker");

    tracker.startActivityTracking();
    await vi.advanceTimersByTimeAsync(30_000);

    expect(tracker.drainPendingAlerts()).toEqual([]);
    tracker.stopActivityTracking();
  });

  it("queues an alert once a flagged window is polled", async () => {
    vi.doMock("get-windows", () => ({
      activeWindow: vi.fn().mockResolvedValue({ title: "Facebook", owner: { name: "Chrome" } }),
    }));
    const tracker = await import("../activityTracker");
    tracker.setActivityWatchlist(["facebook.com"]);

    tracker.startActivityTracking();
    await vi.advanceTimersByTimeAsync(10_000);

    const alerts = tracker.drainPendingAlerts();
    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.matched_term).toBe("facebook.com");
    tracker.stopActivityTracking();
  });

  it("does not queue a new alert every tick for the SAME continuous flagged focus", async () => {
    vi.doMock("get-windows", () => ({
      activeWindow: vi.fn().mockResolvedValue({ title: "Facebook", owner: { name: "Chrome" } }),
    }));
    const tracker = await import("../activityTracker");
    tracker.setActivityWatchlist(["facebook.com"]);

    tracker.startActivityTracking();
    await vi.advanceTimersByTimeAsync(50_000); // 5 poll ticks at 10s each

    expect(tracker.drainPendingAlerts()).toHaveLength(1);
    tracker.stopActivityTracking();
  });

  it("re-alerts if focus returns to a flagged window after leaving it", async () => {
    const activeWindow = vi.fn();
    vi.doMock("get-windows", () => ({ activeWindow }));
    const tracker = await import("../activityTracker");
    tracker.setActivityWatchlist(["facebook.com"]);

    activeWindow.mockResolvedValue({ title: "Facebook", owner: { name: "Chrome" } });
    tracker.startActivityTracking();
    await vi.advanceTimersByTimeAsync(10_000);

    activeWindow.mockResolvedValue({ title: "Report.docx", owner: { name: "WINWORD" } });
    await vi.advanceTimersByTimeAsync(10_000);

    activeWindow.mockResolvedValue({ title: "Facebook", owner: { name: "Chrome" } });
    await vi.advanceTimersByTimeAsync(10_000);

    expect(tracker.drainPendingAlerts()).toHaveLength(2);
    tracker.stopActivityTracking();
  });

  it("drainPendingAlerts empties the queue — a second drain call returns nothing new", async () => {
    vi.doMock("get-windows", () => ({
      activeWindow: vi.fn().mockResolvedValue({ title: "Facebook", owner: { name: "Chrome" } }),
    }));
    const tracker = await import("../activityTracker");
    tracker.setActivityWatchlist(["facebook.com"]);
    tracker.startActivityTracking();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(tracker.drainPendingAlerts()).toHaveLength(1);
    expect(tracker.drainPendingAlerts()).toEqual([]);
    tracker.stopActivityTracking();
  });

  it("fails silently (no throw, no alerts) if the native module rejects", async () => {
    vi.doMock("get-windows", () => ({
      activeWindow: vi.fn().mockRejectedValue(new Error("native binary failed to load")),
    }));
    const tracker = await import("../activityTracker");
    tracker.setActivityWatchlist(["facebook.com"]);
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    tracker.startActivityTracking();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(tracker.drainPendingAlerts()).toEqual([]);
    expect(errSpy).toHaveBeenCalled();
    tracker.stopActivityTracking();
    errSpy.mockRestore();
  });

  it("stopActivityTracking halts polling entirely", async () => {
    const activeWindow = vi.fn().mockResolvedValue({ title: "Facebook", owner: { name: "Chrome" } });
    vi.doMock("get-windows", () => ({ activeWindow }));
    const tracker = await import("../activityTracker");
    tracker.setActivityWatchlist(["facebook.com"]);

    tracker.startActivityTracking();
    await vi.advanceTimersByTimeAsync(10_000);
    tracker.stopActivityTracking();
    tracker.drainPendingAlerts();
    const callsBeforeStop = activeWindow.mock.calls.length;

    await vi.advanceTimersByTimeAsync(60_000);

    expect(activeWindow.mock.calls.length).toBe(callsBeforeStop);
  });

  it("starting twice in a row does not create duplicate poll intervals", async () => {
    const activeWindow = vi.fn().mockResolvedValue(undefined);
    vi.doMock("get-windows", () => ({ activeWindow }));
    const tracker = await import("../activityTracker");
    tracker.setActivityWatchlist(["facebook.com"]);

    tracker.startActivityTracking();
    tracker.startActivityTracking(); // idempotent — must not double the interval
    await vi.advanceTimersByTimeAsync(10_000);

    expect(activeWindow.mock.calls.length).toBe(1);
    tracker.stopActivityTracking();
  });
});

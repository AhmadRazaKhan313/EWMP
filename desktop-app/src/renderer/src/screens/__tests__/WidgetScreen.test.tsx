/**
 * The floating desktop widget: states, buttons, and staying in step with the
 * server (the website / main window can change the work session at any time).
 *
 * Run:  cd desktop-app && npm test -- WidgetScreen
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../../services/authService", () => ({ hasStoredSession: vi.fn() }));

import { hasStoredSession } from "../../services/authService";
import WidgetScreen from "../WidgetScreen";
import { useTimerStore, workSessionService, type WorkSession } from "../../store/timerStore";

const signedIn = hasStoredSession as unknown as ReturnType<typeof vi.fn>;

function session(over: Partial<WorkSession> = {}): WorkSession {
  return {
    id: "s1", employee_id: "e1",
    started_at: new Date(Date.now() - 2 * 3600_000).toISOString(),   // checked in 2 h ago
    ended_at: null, status: "active", total_minutes: null,
    total_break_minutes: 0, total_break_seconds: 0, current_break_started_at: null,
    ...over,
  };
}

const widget = { hide: vi.fn(), minimize: vi.fn(), toggle: vi.fn(), isVisible: vi.fn(), openApp: vi.fn() };
// What the main process sends when ANOTHER window of the app changed the attendance state.
let nudge: (() => void) | null = null;
const unsubscribe = vi.fn();
const attendance = {
  notifyChanged: vi.fn(),
  onChanged: vi.fn((cb: () => void) => { nudge = cb; return unsubscribe; }),
};

function resetStore(): void {
  useTimerStore.setState({
    status: "loading", sessionId: null, startedAt: null,
    elapsedSeconds: 0, breakSeconds: 0, completedBreakSeconds: 0, breakStartedAt: null,
    error: null, breakTypes: [], todaysBreaks: [],
  });
}

const label = (): string => screen.getByTestId("widget-status-label").textContent ?? "";
const work = (): string => screen.getByTestId("widget-working-hours").textContent ?? "";
const brk = (): string => screen.getByTestId("widget-break-time").textContent ?? "";

describe("WidgetScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
    signedIn.mockResolvedValue(true);
    nudge = null;
    (window as unknown as { ewmp: Record<string, unknown> }).ewmp = {
      ...((window as unknown as { ewmp?: Record<string, unknown> }).ewmp ?? {}), widget, attendance,
    };
    vi.spyOn(workSessionService, "listBreaks").mockResolvedValue([]);
    vi.spyOn(workSessionService, "getBreakTypes").mockResolvedValue([]);
  });
  afterEach(() => vi.useRealTimers());

  it("OFFLINE when nobody is checked in: CHECK IN is the action, break is disabled", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
    render(<WidgetScreen />);
    await screen.findByTestId("widget-checkin-button");
    expect(label()).toBe("OFFLINE");
    expect(work()).toBe("00:00:00");
    expect(screen.getByTestId("widget-checkin-button")).toHaveTextContent("CHECK IN");
    expect(screen.getByTestId("widget-break-button")).toBeDisabled();
    expect(screen.getByTestId("widget-break-button")).toHaveTextContent("BREAK ON");
  });

  it("CHECK IN starts a session and the card switches to WORKING / CHECK OUT", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
    const start = vi.spyOn(workSessionService, "start").mockResolvedValue(session({ started_at: new Date().toISOString() }));
    render(<WidgetScreen />);
    await userEvent.click(await screen.findByTestId("widget-checkin-button"));
    expect(start).toHaveBeenCalledTimes(1);
    await screen.findByTestId("widget-checkout-button");
    expect(label()).toBe("WORKING");
    expect(screen.getByTestId("widget-checkout-button")).toHaveTextContent("CHECK OUT");
    expect(screen.getByTestId("widget-break-button")).toBeEnabled();
  });

  it("shows a running session's work time (2 h in) and no break time", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(session());
    render(<WidgetScreen />);
    await waitFor(() => expect(label()).toBe("WORKING"));
    expect(work()).toMatch(/^02:00:0\d$/);
    expect(brk()).toBe("00:00:00");
  });

  it("ON BREAK: work time stops, break time = finished breaks + the current one", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(session({
      status: "on_break", total_break_seconds: 120,
      current_break_started_at: new Date(Date.now() - 300_000).toISOString(),   // 5 min into a break
    }));
    render(<WidgetScreen />);
    await waitFor(() => expect(label()).toBe("ON BREAK"));
    expect(screen.getByTestId("widget-break-button")).toHaveTextContent("BREAK OFF");
    expect(brk()).toMatch(/^00:07:0\d$/);                          // 2 min + 5 min
    expect(work()).toMatch(/^01:5[0-9]:\d\d$/);                    // 2 h - 7 min of break
  });

  it("BREAK ON then BREAK OFF call the break endpoints", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(session());
    const startBreak = vi.spyOn(workSessionService, "startBreak").mockResolvedValue(session({
      status: "on_break", current_break_started_at: new Date().toISOString(),
    }));
    const endBreak = vi.spyOn(workSessionService, "endBreak").mockResolvedValue(session());
    render(<WidgetScreen />);
    await userEvent.click(await screen.findByTestId("widget-break-button"));
    expect(startBreak).toHaveBeenCalledWith("s1", undefined);
    await waitFor(() => expect(label()).toBe("ON BREAK"));
    await userEvent.click(screen.getByTestId("widget-break-button"));
    expect(endBreak).toHaveBeenCalledWith("s1");
    await waitFor(() => expect(label()).toBe("WORKING"));
  });

  it("CHECK OUT ends the session and returns to OFFLINE", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(session());
    const end = vi.spyOn(workSessionService, "end").mockResolvedValue(session({ status: "ended" }));
    render(<WidgetScreen />);
    await userEvent.click(await screen.findByTestId("widget-checkout-button"));
    expect(end).toHaveBeenCalledWith("s1");
    await waitFor(() => expect(label()).toBe("OFFLINE"));
    expect(screen.getByTestId("widget-checkin-button")).toBeInTheDocument();
  });

  it("a failed action shows the server's message on the card", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
    vi.spyOn(workSessionService, "start").mockRejectedValue({ response: { data: { message: "Today's session has already ended." } } });
    render(<WidgetScreen />);
    await userEvent.click(await screen.findByTestId("widget-checkin-button"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Today's session has already ended.");
  });

  it("minimize is a REAL minimize (stays in the taskbar); close hides to the tray", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
    render(<WidgetScreen />);
    await userEvent.click(await screen.findByTestId("widget-minimize-button"));
    expect(widget.minimize).toHaveBeenCalledTimes(1);
    expect(widget.hide).not.toHaveBeenCalled();           // it used to hide -- gone from the taskbar

    await userEvent.click(screen.getByTestId("widget-close-button"));
    expect(widget.hide).toHaveBeenCalledTimes(1);
    expect(widget.minimize).toHaveBeenCalledTimes(1);
  });

  describe("signed out", () => {
    it("asks the user to sign in instead of offering buttons that would fail", async () => {
      signedIn.mockResolvedValue(false);
      const getActive = vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
      render(<WidgetScreen />);
      expect(await screen.findByText(/Sign in to the EWMP app/)).toBeInTheDocument();
      expect(screen.queryByTestId("widget-checkin-button")).not.toBeInTheDocument();
      expect(screen.queryByTestId("widget-break-button")).not.toBeInTheDocument();
      expect(getActive).not.toHaveBeenCalled();                    // no pointless 401
      await userEvent.click(screen.getByTestId("widget-open-app-button"));
      expect(widget.openApp).toHaveBeenCalledTimes(1);
    });
  });

  describe("one attendance state across the app, the widget and the website", () => {
    it("re-reads the server AT ONCE when the main window changes something (no waiting for a poll)", async () => {
      const getActive = vi.spyOn(workSessionService, "getActive").mockResolvedValue(session());
      render(<WidgetScreen />);
      await waitFor(() => expect(label()).toBe("WORKING"));

      // The Desktop App starts a break: the main process nudges the widget.
      getActive.mockResolvedValue(session({ status: "on_break", current_break_started_at: new Date().toISOString() }));
      await act(async () => { nudge?.(); });
      await waitFor(() => expect(label()).toBe("ON BREAK"));
      expect(screen.getByTestId("widget-break-button")).toHaveTextContent("BREAK OFF");

      // ...and ends it.
      getActive.mockResolvedValue(session());
      await act(async () => { nudge?.(); });
      await waitFor(() => expect(label()).toBe("WORKING"));
    });

    it("a break started in the widget tells the other windows", async () => {
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(session());
      vi.spyOn(workSessionService, "startBreak").mockResolvedValue(session({ status: "on_break", current_break_started_at: new Date().toISOString() }));
      render(<WidgetScreen />);
      await userEvent.click(await screen.findByTestId("widget-break-button"));
      await waitFor(() => expect(label()).toBe("ON BREAK"));
      expect(attendance.notifyChanged).toHaveBeenCalledTimes(1);
    });

    it("a double-click on BREAK ON sends one request", async () => {
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(session());
      let resolve!: (s: WorkSession) => void;
      const startBreak = vi.spyOn(workSessionService, "startBreak").mockReturnValue(new Promise((r) => { resolve = r; }));
      render(<WidgetScreen />);
      const button = await screen.findByTestId("widget-break-button");
      await userEvent.click(button);
      await userEvent.click(button);
      expect(startBreak).toHaveBeenCalledTimes(1);
      expect(button).toBeDisabled();                         // visibly busy while it runs
      await act(async () => { resolve(session({ status: "on_break", current_break_started_at: new Date().toISOString() })); });
      await waitFor(() => expect(label()).toBe("ON BREAK"));
    });

    it("listens once, and stops listening when the widget unmounts", async () => {
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
      const { unmount } = render(<WidgetScreen />);
      await screen.findByTestId("widget-checkin-button");
      expect(attendance.onChanged).toHaveBeenCalledTimes(1);
      unmount();
      expect(unsubscribe).toHaveBeenCalledTimes(1);
    });

    it("opens showing the CURRENT server state, not a remembered one (break started on the website earlier)", async () => {
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(session({
        status: "on_break", total_break_seconds: 0,
        current_break_started_at: new Date(Date.now() - 120_000).toISOString(),
      }));
      render(<WidgetScreen />);
      await waitFor(() => expect(label()).toBe("ON BREAK"));
      expect(brk()).toMatch(/^00:02:0\d$/);
    });
  });

  describe("staying in sync with the server", () => {
    beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));

    it("notices a check-in made elsewhere (website / main window) without any click", async () => {
      const getActive = vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
      render(<WidgetScreen />);
      await waitFor(() => expect(label()).toBe("OFFLINE"));
      getActive.mockResolvedValue(session());                       // someone checks in on the website
      await act(async () => { await vi.advanceTimersByTimeAsync(15_100); });
      await waitFor(() => expect(label()).toBe("WORKING"));
    });

    it("notices a check-out made elsewhere", async () => {
      const getActive = vi.spyOn(workSessionService, "getActive").mockResolvedValue(session());
      render(<WidgetScreen />);
      await waitFor(() => expect(label()).toBe("WORKING"));
      getActive.mockResolvedValue(null);
      await act(async () => { await vi.advanceTimersByTimeAsync(15_100); });
      await waitFor(() => expect(label()).toBe("OFFLINE"));
    });

    it("a failed re-sync (network blip) does NOT blank a running timer", async () => {
      const getActive = vi.spyOn(workSessionService, "getActive").mockResolvedValue(session());
      render(<WidgetScreen />);
      await waitFor(() => expect(label()).toBe("WORKING"));
      getActive.mockRejectedValue(new Error("Network Error"));
      await act(async () => { await vi.advanceTimersByTimeAsync(15_100); });
      expect(label()).toBe("WORKING");
      expect(work()).not.toBe("00:00:00");
    });

    it("signing out in the main window resets the widget; signing back in reloads it", async () => {
      vi.spyOn(workSessionService, "getActive").mockResolvedValue(session());
      render(<WidgetScreen />);
      await waitFor(() => expect(label()).toBe("WORKING"));

      signedIn.mockResolvedValue(false);
      await act(async () => { await vi.advanceTimersByTimeAsync(15_100); });
      expect(await screen.findByText(/Sign in to the EWMP app/)).toBeInTheDocument();
      expect(label()).toBe("OFFLINE");
      expect(work()).toBe("00:00:00");

      signedIn.mockResolvedValue(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(15_100); });
      await waitFor(() => expect(label()).toBe("WORKING"));
    });
  });
});

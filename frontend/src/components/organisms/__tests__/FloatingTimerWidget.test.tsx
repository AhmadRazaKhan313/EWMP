/**
 * The website's floating check-in / break widget.
 *
 * Run:  cd frontend && npm test -- FloatingTimerWidget
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { getMock, postMock, toastError, toastSuccess } = vi.hoisted(() => ({
  getMock: vi.fn(), postMock: vi.fn(), toastError: vi.fn(), toastSuccess: vi.fn(),
}));
vi.mock("@/services/api-client", () => ({ default: { get: getMock, post: postMock } }));
vi.mock("sonner", () => ({ toast: { error: toastError, success: toastSuccess } }));

import { useAuthStore } from "@/store/auth.store";
import { FloatingTimerWidget, COLLAPSED_KEY } from "../FloatingTimerWidget";

function signIn(over: Record<string, unknown> = {}) {
  useAuthStore.setState({
    isAuthenticated: true,
    user: { id: "u1", has_employee_profile: true, must_change_password: false, ...over } as never,
  });
}

const session = (over: Record<string, unknown> = {}) => ({
  id: "s1",
  started_at: new Date(Date.now() - 2 * 3600_000).toISOString(),   // checked in 2 h ago
  status: "active", total_break_seconds: 0, current_break_started_at: null, ...over,
});

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><FloatingTimerWidget /></QueryClientProvider>);
}

const status = () => screen.getByTestId("floating-timer-status").textContent;
const work = () => screen.getByTestId("floating-timer-work").textContent ?? "";
const brk = () => screen.getByTestId("floating-timer-break").textContent ?? "";

describe("FloatingTimerWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    signIn();
    getMock.mockResolvedValue({ data: null });
    postMock.mockResolvedValue({ data: {} });
  });
  afterEach(() => vi.useRealTimers());

  it("is not shown to an account with no employee profile (it could never check in)", async () => {
    signIn({ has_employee_profile: false });
    renderWidget();
    await act(async () => {});
    expect(screen.queryByTestId("floating-timer-check")).not.toBeInTheDocument();
    expect(getMock).not.toHaveBeenCalled();
  });

  it("is not shown while a temporary password still has to be changed", async () => {
    signIn({ must_change_password: true });
    renderWidget();
    await act(async () => {});
    expect(screen.queryByTestId("floating-timer-check")).not.toBeInTheDocument();
  });

  it("OFFLINE: CHECK IN is offered, break is disabled; CHECK IN posts a manual check-in", async () => {
    renderWidget();
    const check = await screen.findByTestId("floating-timer-check");
    await waitFor(() => expect(status()).toBe("OFFLINE"));
    expect(check).toHaveTextContent("CHECK IN");
    expect(work()).toBe("00:00:00");
    expect(screen.getByTestId("floating-timer-break-button")).toBeDisabled();

    await userEvent.click(check);
    expect(postMock).toHaveBeenCalledWith("/attendance/check-in", { method: "manual" });
  });

  it("WORKING: shows the work time since check-in, CHECK OUT, and break enabled", async () => {
    getMock.mockResolvedValue({ data: session() });
    renderWidget();
    await waitFor(() => expect(status()).toBe("WORKING"));
    expect(work()).toMatch(/^02:00:0\d$/);
    expect(brk()).toBe("00:00:00");
    expect(screen.getByTestId("floating-timer-check")).toHaveTextContent("CHECK OUT");
    expect(screen.getByTestId("floating-timer-break-button")).toBeEnabled();

    await userEvent.click(screen.getByTestId("floating-timer-check"));
    expect(postMock).toHaveBeenCalledWith("/attendance/check-out", {});
  });

  it("ON BREAK: work time excludes breaks, break time = finished + current", async () => {
    getMock.mockResolvedValue({ data: session({
      status: "on_break", total_break_seconds: 120,
      current_break_started_at: new Date(Date.now() - 300_000).toISOString(),   // 5 min into a break
    }) });
    renderWidget();
    await waitFor(() => expect(status()).toBe("ON BREAK"));
    expect(brk()).toMatch(/^00:07:0\d$/);                         // 2 min + 5 min
    expect(work()).toMatch(/^01:5[0-9]:\d\d$/);                   // 2 h - 7 min
    expect(screen.getByTestId("floating-timer-break-button")).toHaveTextContent("BREAK OFF");
  });

  it("BREAK ON and BREAK OFF call the same endpoints the desktop app uses", async () => {
    getMock.mockResolvedValue({ data: session() });
    renderWidget();

    // Like the real server: once the break starts, the next read says on_break.
    postMock.mockImplementationOnce(async () => {
      getMock.mockResolvedValue({ data: session({ status: "on_break", current_break_started_at: new Date().toISOString() }) });
      return { data: {} };
    });
    await userEvent.click(await screen.findByTestId("floating-timer-break-button"));
    expect(postMock).toHaveBeenCalledWith("/work-sessions/s1/break/start", { break_type_id: null });
    await waitFor(() => expect(screen.getByTestId("floating-timer-break-button")).toHaveTextContent("BREAK OFF"));

    postMock.mockImplementationOnce(async () => {
      getMock.mockResolvedValue({ data: session() });
      return { data: {} };
    });
    await userEvent.click(screen.getByTestId("floating-timer-break-button"));
    expect(postMock).toHaveBeenCalledWith("/work-sessions/s1/break/end");
    await waitFor(() => expect(screen.getByTestId("floating-timer-break-button")).toHaveTextContent("BREAK ON"));
  });

  it("shows the server's message when an action fails", async () => {
    postMock.mockRejectedValue({ response: { data: { message: "Today's session has already ended." } } });
    renderWidget();
    await userEvent.click(await screen.findByTestId("floating-timer-check"));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Today's session has already ended."));
  });

  it("picks up a check-in made in the desktop app on the next poll", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWidget();
    await waitFor(() => expect(status()).toBe("OFFLINE"));
    getMock.mockResolvedValue({ data: session() });                // checked in on the desktop
    await act(async () => { await vi.advanceTimersByTimeAsync(15_100); });
    await waitFor(() => expect(status()).toBe("WORKING"));
  });

  describe("one attendance state with the desktop app and widget", () => {
    it("re-reads the server every few seconds (not every 15)", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      renderWidget();
      await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1));
      await act(async () => { await vi.advanceTimersByTimeAsync(5_100); });
      expect(getMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    it("re-reads when the tab becomes visible again (the app-wide default is to NOT refetch on focus)", async () => {
      renderWidget();
      await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1));
      getMock.mockResolvedValue({ data: session({ status: "on_break", current_break_started_at: new Date().toISOString() }) });
      await act(async () => { window.dispatchEvent(new Event("visibilitychange")); });   // React Query listens on window
      await waitFor(() => expect(status()).toBe("ON BREAK"));    // a break started in the desktop widget meanwhile
    });

    it("shows a break started in the desktop widget, then its end, without any click here", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      getMock.mockResolvedValue({ data: session() });
      renderWidget();
      await waitFor(() => expect(status()).toBe("WORKING"));

      getMock.mockResolvedValue({ data: session({ status: "on_break", current_break_started_at: new Date().toISOString() }) });
      await act(async () => { await vi.advanceTimersByTimeAsync(5_100); });
      await waitFor(() => expect(status()).toBe("ON BREAK"));

      getMock.mockResolvedValue({ data: session({ total_break_seconds: 5 }) });
      await act(async () => { await vi.advanceTimersByTimeAsync(5_100); });
      await waitFor(() => expect(status()).toBe("WORKING"));
    });

    it("shows a check-out made elsewhere", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      getMock.mockResolvedValue({ data: session() });
      renderWidget();
      await waitFor(() => expect(status()).toBe("WORKING"));
      getMock.mockResolvedValue({ data: null });
      await act(async () => { await vi.advanceTimersByTimeAsync(5_100); });
      await waitFor(() => expect(status()).toBe("OFFLINE"));
      expect(work()).toBe("00:00:00");
    });

    it("counts from the SERVER's clock, so a PC with a wrong clock still agrees with the desktop app", async () => {
      const serverNow = Date.now() - 600_000;                      // this PC is 10 minutes ahead of the server
      getMock.mockResolvedValue({ data: session({
        started_at: new Date(serverNow - 7200_000).toISOString(),  // 2 h before "server now"
        server_time: new Date(serverNow).toISOString(),
      }) });
      renderWidget();
      await waitFor(() => expect(status()).toBe("WORKING"));
      expect(work()).toMatch(/^02:00:0\d$/);                       // 2:00:00 -- not 2:10:00
    });

    it("a double-click on BREAK ON sends one request", async () => {
      getMock.mockResolvedValue({ data: session() });
      let resolve!: (v: unknown) => void;
      postMock.mockReturnValue(new Promise((r) => { resolve = r; }));
      renderWidget();
      const button = await screen.findByTestId("floating-timer-break-button");
      await userEvent.click(button);
      await userEvent.click(button);
      expect(postMock).toHaveBeenCalledTimes(1);
      expect(button).toBeDisabled();
      await act(async () => { resolve({ data: {} }); });
    });
  });

  describe("minimise", () => {
    it("collapses to a pill, remembers it, and opens again on click", async () => {
      getMock.mockResolvedValue({ data: session() });
      const first = renderWidget();
      await userEvent.click(await screen.findByTestId("floating-timer-minimize"));

      const pill = screen.getByTestId("floating-timer-pill");
      expect(pill).toHaveTextContent("WORKING");
      expect(screen.queryByTestId("floating-timer-check")).not.toBeInTheDocument();
      expect(localStorage.getItem(COLLAPSED_KEY)).toBe("1");

      first.unmount();                                              // a later visit
      renderWidget();
      expect(await screen.findByTestId("floating-timer-pill")).toBeInTheDocument();

      await userEvent.click(screen.getByTestId("floating-timer-pill"));
      expect(await screen.findByTestId("floating-timer-check")).toBeInTheDocument();
      expect(localStorage.getItem(COLLAPSED_KEY)).toBe("0");
    });
  });
});

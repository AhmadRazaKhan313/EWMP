import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CheckInWidget from "../CheckInWidget";
import { useTimerStore, workSessionService } from "../../store/timerStore";

function reset(): void {
  useTimerStore.setState({ status: "loading", sessionId: null, startedAt: null, elapsedSeconds: 0, error: null });
}

describe("CheckInWidget", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("shows a blue 'Check In' button when not checked in", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
    render(<CheckInWidget />);

    const button = await screen.findByTestId("checkin-button");
    expect(button).toHaveTextContent("Check In");
    expect(button.className).toMatch(/bg-\[hsl\(var\(--primary\)\)\]/);
    expect(screen.queryByTestId("timer-display")).not.toBeInTheDocument();
  });

  it("clicking Check In turns the button red, changes its title, and starts the timer", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
    vi.spyOn(workSessionService, "start").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: new Date().toISOString(), ended_at: null, status: "active", total_minutes: null,
    });
    render(<CheckInWidget />);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId("checkin-button"));

    await waitFor(() => {
      const button = screen.getByTestId("checkin-button");
      expect(button).toHaveTextContent("Check Out");
      expect(button.className).toMatch(/bg-red-600/);
    });
    expect(screen.getByTestId("timer-display")).toHaveTextContent(/\d{2}:\d{2}:\d{2}/);
  });

  it("restores an already-active session on load, showing red button + timer immediately", async () => {
    const startedAt = new Date(Date.now() - 10_000).toISOString();
    vi.spyOn(workSessionService, "getActive").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: startedAt, ended_at: null, status: "active", total_minutes: null,
    });
    render(<CheckInWidget />);

    await waitFor(() => {
      expect(screen.getByTestId("checkin-button")).toHaveTextContent("Check Out");
    });
    expect(screen.getByTestId("timer-display")).toBeInTheDocument();
  });

  it("clicking Check Out returns the button to blue 'Check In' and hides the timer", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: new Date().toISOString(), ended_at: null, status: "active", total_minutes: null,
    });
    vi.spyOn(workSessionService, "end").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: "", ended_at: new Date().toISOString(), status: "ended", total_minutes: 1,
    });
    render(<CheckInWidget />);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId("checkin-button")).toHaveTextContent("Check Out"));
    await user.click(screen.getByTestId("checkin-button"));

    await waitFor(() => {
      const button = screen.getByTestId("checkin-button");
      expect(button).toHaveTextContent("Check In");
      expect(button.className).toMatch(/bg-\[hsl\(var\(--primary\)\)\]/);
    });
    expect(screen.queryByTestId("timer-display")).not.toBeInTheDocument();
  });

  it("shows an error message if check-in fails, without crashing", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
    vi.spyOn(workSessionService, "start").mockRejectedValue(new Error("Server unreachable"));
    render(<CheckInWidget />);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId("checkin-button"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Server unreachable");
  });

  it("shows the Break button once checked in, and clicking it pauses the timer amber", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: new Date().toISOString(), ended_at: null, status: "active", total_minutes: null,
    });
    vi.spyOn(workSessionService, "startBreak").mockResolvedValue({ status: "on_break" });
    render(<CheckInWidget />);
    const user = userEvent.setup();

    const breakButton = await screen.findByTestId("break-button");
    expect(breakButton).toHaveTextContent("Take Break");

    await user.click(breakButton);

    await waitFor(() => {
      expect(screen.getByTestId("break-button")).toHaveTextContent("Resume Work");
    });
    expect(screen.getByTestId("break-label")).toHaveTextContent("On break");
    expect(screen.getByTestId("timer-display").className).toMatch(/text-amber-500/);
    // Check In/Out button must still say "Check Out" — break doesn't end the session
    expect(screen.getByTestId("checkin-button")).toHaveTextContent("Check Out");
  });

  it("clicking Resume Work while on break returns to the active state", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue({
      id: "s1", employee_id: "e1", started_at: new Date().toISOString(), ended_at: null, status: "on_break", total_minutes: null,
    });
    vi.spyOn(workSessionService, "endBreak").mockResolvedValue({ status: "active" });
    render(<CheckInWidget />);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId("break-button")).toHaveTextContent("Resume Work"));
    await user.click(screen.getByTestId("break-button"));

    await waitFor(() => {
      expect(screen.getByTestId("break-button")).toHaveTextContent("Take Break");
    });
    expect(screen.queryByTestId("break-label")).not.toBeInTheDocument();
  });

  it("hides the Break button entirely when not checked in", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
    render(<CheckInWidget />);

    await screen.findByTestId("checkin-button");
    expect(screen.queryByTestId("break-button")).not.toBeInTheDocument();
  });

  it("shows the backend's 409 message when Check In is attempted after today's session already ended", async () => {
    vi.spyOn(workSessionService, "getActive").mockResolvedValue(null);
    vi.spyOn(workSessionService, "start").mockRejectedValue({
      response: { data: { message: "You've already checked out for today. Use Break instead of Check Out for short pauses." } },
    });
    render(<CheckInWidget />);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId("checkin-button"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already checked out for today/);
  });
});

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import BreakLockScreen, { BreakWarningBanner } from "../BreakLockScreen";
import type { BreakLockState } from "../../hooks/useBreakLock";

const base = (over: Partial<BreakLockState> = {}): BreakLockState => ({
  phase: "active", locked: true, secondsToStart: 0, secondsToEnd: 1805, requestStatus: null,
  requestUnlock: vi.fn().mockResolvedValue(undefined), requesting: false, error: null, ...over,
});

describe("BreakLockScreen", () => {
  it("shows the countdown and sends the reason with the unlock request", async () => {
    const s = base();
    render(<BreakLockScreen state={s} />);
    expect(screen.getByTestId("break-countdown").textContent).toBe("30:05");
    await userEvent.type(screen.getByLabelText("Reason"), "client call");
    await userEvent.click(screen.getByRole("button", { name: "Request unlock" }));
    expect(s.requestUnlock).toHaveBeenCalledWith("client call");
  });
  it("waits quietly while pending", () => {
    render(<BreakLockScreen state={base({ requestStatus: "pending" })} />);
    expect(screen.getByText(/Waiting for your admin/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("says so when denied and allows asking again", () => {
    render(<BreakLockScreen state={base({ requestStatus: "denied" })} />);
    expect(screen.getByText(/was denied/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ask again" })).toBeTruthy();
  });
  it("warning banner counts down", () => {
    render(<BreakWarningBanner secondsToStart={125} />);
    expect(screen.getByRole("status").textContent).toContain("02:05");
  });
});

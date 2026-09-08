/**
 * Regression tests for the attendance check-in widget.
 *
 * Covers bug C4 (manual check-in/out must work with no geolocation at all,
 * geo-fence is an optional secondary action) plus the live-status rewrite:
 * a single Check In/Check Out button driven by /work-sessions/me/active
 * (shared with the desktop app), with separate working/break timers.
 *
 * Run:  cd frontend && npm test -- CheckInWidget
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CheckInWidget } from "../CheckInWidget";

vi.mock("@/services/api-client", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: null }),
    post: vi.fn().mockResolvedValue({ data: { late_minutes: 0, overtime_minutes: 0, total_minutes: 0 } }),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import apiClient from "@/services/api-client";
import { toast } from "sonner";

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CheckInWidget />
    </QueryClientProvider>,
  );
}

function mockActiveSession(overrides: Partial<{
  status: "active" | "on_break"; started_at: string; total_break_minutes: number;
  current_break_started_at: string | null;
}> = {}) {
  (apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: {
      id: "s1", employee_id: "e1", status: "active", total_minutes: null,
      total_break_minutes: 0, current_break_started_at: null,
      started_at: new Date().toISOString(),
      ...overrides,
    },
  });
}

describe("CheckInWidget — manual check-in (bug C4)", () => {
  const originalGeolocation = navigator.geolocation;

  beforeEach(() => {
    vi.clearAllMocks();
    (apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: null }); // not checked in by default
  });

  afterEach(() => {
    Object.defineProperty(navigator, "geolocation", {
      value: originalGeolocation,
      configurable: true,
    });
  });

  it("renders a manual check-in action that needs no geolocation at all", async () => {
    Object.defineProperty(navigator, "geolocation", { value: undefined, configurable: true });

    renderWidget();
    const user = userEvent.setup();

    const manualCheckIn = await screen.findByTestId("checkin-button");
    expect(manualCheckIn).toHaveTextContent("Check In");
    await user.click(manualCheckIn);

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        "/attendance/check-in",
        expect.objectContaining({ method: "manual" }),
      );
    });

    // Must NOT include geo coordinates on the manual path.
    const calls = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls as unknown as [string, Record<string, unknown>][];
    const [, body] = calls[0]!;
    expect(body).not.toHaveProperty("latitude");
    expect(body).not.toHaveProperty("longitude");
  });

  it("renders a manual check-out action that needs no geolocation at all", async () => {
    Object.defineProperty(navigator, "geolocation", { value: undefined, configurable: true });
    mockActiveSession(); // already checked in

    renderWidget();
    const user = userEvent.setup();

    const manualCheckOut = await screen.findByTestId("checkin-button");
    await waitFor(() => expect(manualCheckOut).toHaveTextContent("Check Out"));
    await user.click(manualCheckOut);

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith("/attendance/check-out", expect.anything());
    });

    const calls = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls as unknown as [string, Record<string, unknown>][];
    const [, body] = calls[0]!;
    expect(body).not.toHaveProperty("latitude");
    expect(body).not.toHaveProperty("longitude");
  });

  it("never calls navigator.geolocation for the manual action", async () => {
    const getCurrentPosition = vi.fn();
    Object.defineProperty(navigator, "geolocation", {
      value: { getCurrentPosition },
      configurable: true,
    });

    renderWidget();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId("checkin-button"));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());

    expect(getCurrentPosition).not.toHaveBeenCalled();
  });

  it("still offers geo-fence check-in as an optional secondary action", async () => {
    const getCurrentPosition = vi.fn((success: PositionCallback) =>
      success({ coords: { latitude: 1, longitude: 2 } } as GeolocationPosition),
    );
    Object.defineProperty(navigator, "geolocation", {
      value: { getCurrentPosition },
      configurable: true,
    });

    renderWidget();
    const user = userEvent.setup();

    const geoButton = await screen.findByRole("button", { name: /use my location|geo/i });
    await user.click(geoButton);

    await waitFor(() => expect(getCurrentPosition).toHaveBeenCalled());
    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        "/attendance/check-in",
        expect.objectContaining({ method: "geo", latitude: 1, longitude: 2 }),
      );
    });
  });
});

describe("CheckInWidget — live status + timers (synced with desktop app)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows Check In (not Check Out) when no active session exists anywhere", async () => {
    (apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: null });
    renderWidget();

    const button = await screen.findByTestId("checkin-button");
    expect(button).toHaveTextContent("Check In");
    expect(screen.queryByTestId("timer-display")).not.toBeInTheDocument();
  });

  it("shows Check Out + a red button + a running timer when active (e.g. checked in from the desktop app)", async () => {
    mockActiveSession({ started_at: new Date(Date.now() - 65_000).toISOString() });
    renderWidget();

    await waitFor(() => {
      const button = screen.getByTestId("checkin-button");
      expect(button).toHaveTextContent("Check Out");
      expect(button.className).toMatch(/bg-red-600/);
    });
    expect(screen.getByTestId("timer-display")).toHaveTextContent(/Checked in/);
  });

  it("shows an amber on-break state, distinct from the active state", async () => {
    mockActiveSession({
      status: "on_break",
      started_at: new Date(Date.now() - 300_000).toISOString(),
      current_break_started_at: new Date(Date.now() - 30_000).toISOString(),
    });
    renderWidget();

    await waitFor(() => {
      expect(screen.getByTestId("timer-display")).toHaveTextContent(/On break/);
    });
  });

  it("shows the total time worked in the toast after checking out", async () => {
    mockActiveSession();
    (apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { overtime_minutes: 0, total_minutes: 95 },
    });
    renderWidget();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId("checkin-button")).toHaveTextContent("Check Out"));
    await user.click(screen.getByTestId("checkin-button"));

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(expect.stringMatching(/1h 35m/));
    });
  });
});

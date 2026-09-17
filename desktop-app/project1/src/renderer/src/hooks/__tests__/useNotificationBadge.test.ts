import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useNotificationBadge } from "../useNotificationBadge";
import * as notificationsService from "../../services/notificationsService";

vi.mock("../../services/notificationsService");

describe("useNotificationBadge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    window.ewmp.tray.setBadgeCount = vi.fn().mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does nothing (zeroes the badge) when disabled", async () => {
    renderHook(() => useNotificationBadge(false));
    await vi.waitFor(() => expect(window.ewmp.tray.setBadgeCount).toHaveBeenCalledWith(0));
    expect(notificationsService.getUnreadNotificationCount).not.toHaveBeenCalled();
  });

  it("polls immediately on mount and pushes the count to the tray when enabled", async () => {
    vi.mocked(notificationsService.getUnreadNotificationCount).mockResolvedValue(4);
    renderHook(() => useNotificationBadge(true));
    await vi.waitFor(() => expect(window.ewmp.tray.setBadgeCount).toHaveBeenCalledWith(4));
  });

  it("polls again every 60 seconds while enabled", async () => {
    vi.mocked(notificationsService.getUnreadNotificationCount).mockResolvedValue(1);
    renderHook(() => useNotificationBadge(true));
    await vi.waitFor(() => expect(notificationsService.getUnreadNotificationCount).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(60_000);
    expect(notificationsService.getUnreadNotificationCount).toHaveBeenCalledTimes(2);
  });

  it("swallows a failed poll without throwing", async () => {
    vi.mocked(notificationsService.getUnreadNotificationCount).mockRejectedValue(new Error("network down"));
    expect(() => renderHook(() => useNotificationBadge(true))).not.toThrow();
  });

  it("stops polling on unmount", async () => {
    vi.mocked(notificationsService.getUnreadNotificationCount).mockResolvedValue(2);
    const { unmount } = renderHook(() => useNotificationBadge(true));
    await vi.waitFor(() => expect(notificationsService.getUnreadNotificationCount).toHaveBeenCalledTimes(1));

    unmount();
    await vi.advanceTimersByTimeAsync(180_000);
    expect(notificationsService.getUnreadNotificationCount).toHaveBeenCalledTimes(1);
  });
});

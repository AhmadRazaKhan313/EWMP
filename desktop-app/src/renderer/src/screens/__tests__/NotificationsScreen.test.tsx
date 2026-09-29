import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import NotificationsScreen from "../NotificationsScreen";
import * as notificationsService from "../../services/notificationsService";

vi.mock("../../services/notificationsService");

const NOTIFS = [
  {
    id: "n-1", title: "Leave request approved", body: "Your leave was approved.", type: "leave_approved",
    icon: null, action_url: null, metadata: {}, is_read: false, read_at: null,
    created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
  },
  {
    id: "n-2", title: "Welcome to EWMP", body: null, type: "general",
    icon: null, action_url: null, metadata: {}, is_read: true, read_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
  },
];

function renderWithClient(ui: React.ReactElement): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("NotificationsScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(notificationsService.listNotifications).mockResolvedValue({
      items: NOTIFS, total: 2, unread_count: 1,
    });
  });

  it("lists notifications with a Mark read action only on the unread one", async () => {
    renderWithClient(<NotificationsScreen />);
    const list = await screen.findByTestId("notifications-list");
    await waitFor(() => expect(list).toHaveTextContent("Leave request approved"));
    expect(list).toHaveTextContent("Welcome to EWMP");
    expect(screen.getByTestId("mark-read-n-1")).toBeInTheDocument();
    expect(screen.queryByTestId("mark-read-n-2")).not.toBeInTheDocument();
  });

  it("marks a single notification read and refetches", async () => {
    vi.mocked(notificationsService.markNotificationRead).mockResolvedValue(undefined);
    renderWithClient(<NotificationsScreen />);
    await screen.findByTestId("mark-read-n-1");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("mark-read-n-1"));

    // react-query 5.x passes a (variables, context) pair to mutationFn —
    // only the first argument is ours to assert on.
    await waitFor(() => expect(notificationsService.markNotificationRead).toHaveBeenCalled());
    expect(vi.mocked(notificationsService.markNotificationRead).mock.calls[0]?.[0]).toBe("n-1");
  });

  it("mark-all-read is disabled when there are no unread notifications", async () => {
    vi.mocked(notificationsService.listNotifications).mockResolvedValue({ items: NOTIFS, total: 2, unread_count: 0 });
    renderWithClient(<NotificationsScreen />);
    await waitFor(() => expect(screen.getByTestId("mark-all-read-button")).toBeDisabled());
  });

  it("calls markAllNotificationsRead when clicked", async () => {
    vi.mocked(notificationsService.markAllNotificationsRead).mockResolvedValue(undefined);
    renderWithClient(<NotificationsScreen />);
    await screen.findByTestId("notifications-list");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("mark-all-read-button"));
    await waitFor(() => expect(notificationsService.markAllNotificationsRead).toHaveBeenCalledTimes(1));
  });

  it("re-queries with unread_only=true when the toggle is checked", async () => {
    renderWithClient(<NotificationsScreen />);
    await screen.findByTestId("notifications-list");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("unread-only-toggle"));

    await waitFor(() => expect(notificationsService.listNotifications).toHaveBeenCalledWith(true));
  });

  it("shows an empty state when there are no notifications", async () => {
    vi.mocked(notificationsService.listNotifications).mockResolvedValue({ items: [], total: 0, unread_count: 0 });
    renderWithClient(<NotificationsScreen />);
    expect(await screen.findByText(/no notifications yet/i)).toBeInTheDocument();
  });
});

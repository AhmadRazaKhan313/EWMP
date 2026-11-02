/**
 * Notifications UI: the bell (count, list, mark read, open link) and the
 * Settings -> Notifications switches.
 *
 * Run:  cd frontend && npm test -- Notifications
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NotificationBell } from "../NotificationBell";
import { NotificationSettings } from "../NotificationSettings";
import { timeAgo } from "@/services/notifications.service";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
vi.mock("@/services/api-client", () => ({
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
  },
}));

const NOW = new Date().toISOString();
const ITEMS = [
  { id: "n1", title: "New leave request", body: "Ali asked for 2 days of Annual, 2026-10-21 to 2026-10-22.", type: "leave",
    icon: null, action_url: "/leave", metadata: {}, is_read: false, read_at: null, created_at: NOW },
  { id: "n2", title: "Salary paid", body: null, type: "payroll",
    icon: null, action_url: null, metadata: {}, is_read: true, read_at: NOW, created_at: NOW },
];

const PREFS = [
  { key: "leave", label: "Leave", description: "Leave things", enabled: true },
  { key: "payroll", label: "Payroll", description: "Pay things", enabled: false },
];

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  push.mockReset(); get.mockReset(); post.mockReset(); put.mockReset();
  post.mockResolvedValue({});
  get.mockImplementation(async (url: string) => {
    if (url === "/notifications/unread-count") return { data: { unread_count: 1 } };
    if (url === "/notifications") return { data: { items: ITEMS, total: 2, unread_count: 1 } };
    if (url === "/notifications/preferences") return { data: { items: PREFS } };
    throw new Error(`unexpected GET ${url}`);
  });
});

describe("NotificationBell", () => {
  it("shows the unread count on the bell", async () => {
    wrap(<NotificationBell />);
    expect(await screen.findByLabelText("Notifications, 1 unread")).toBeInTheDocument();
  });

  it("opens a list with unread first-class styling and a mark-all button", async () => {
    wrap(<NotificationBell />);
    await userEvent.click(await screen.findByLabelText(/Notifications/));
    expect(await screen.findByText("New leave request")).toBeInTheDocument();
    expect(screen.getByText("Salary paid")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Unread")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Mark all read" })).toBeEnabled();
  });

  it("clicking one marks it read and goes to its page", async () => {
    wrap(<NotificationBell />);
    await userEvent.click(await screen.findByLabelText(/Notifications/));
    await userEvent.click(await screen.findByText("New leave request"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/notifications/n1/read"));
    expect(push).toHaveBeenCalledWith("/leave");
  });

  it("an already-read one does not call mark-read again", async () => {
    wrap(<NotificationBell />);
    await userEvent.click(await screen.findByLabelText(/Notifications/));
    await userEvent.click(await screen.findByText("Salary paid"));
    expect(post).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled(); // no link on this one
  });

  it("Mark all read calls the API", async () => {
    wrap(<NotificationBell />);
    await userEvent.click(await screen.findByLabelText(/Notifications/));
    await userEvent.click(await screen.findByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/notifications/read-all"));
  });

  it("says you're caught up when there is nothing", async () => {
    get.mockImplementation(async (url: string) =>
      url === "/notifications/unread-count" ? { data: { unread_count: 0 } }
        : { data: { items: [], total: 0, unread_count: 0 } });
    wrap(<NotificationBell />);
    await userEvent.click(await screen.findByLabelText("Notifications"));
    expect(await screen.findByText(/all caught up/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark all read" })).toBeDisabled();
  });

  it("has a link to the settings tab", async () => {
    wrap(<NotificationBell />);
    await userEvent.click(await screen.findByLabelText(/Notifications/));
    await userEvent.click(await screen.findByText("Notification settings"));
    expect(push).toHaveBeenCalledWith("/settings?tab=notifications");
  });
});

describe("NotificationSettings", () => {
  it("shows each category with its current switch position", async () => {
    wrap(<NotificationSettings />);
    expect(await screen.findByRole("switch", { name: "Leave" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("switch", { name: "Payroll" })).toHaveAttribute("aria-checked", "false");
  });

  it("flipping a switch saves just that choice", async () => {
    put.mockResolvedValue({ data: { items: [PREFS[0], { ...PREFS[1], enabled: true }] } });
    wrap(<NotificationSettings />);
    await userEvent.click(await screen.findByRole("switch", { name: "Payroll" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/notifications/preferences", { preferences: { payroll: true } }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Payroll" })).toHaveAttribute("aria-checked", "true"));
  });
});

describe("timeAgo", () => {
  const now = new Date("2026-10-21T12:00:00Z").getTime();
  it.each([
    ["2026-10-21T11:59:40Z", "just now"],
    ["2026-10-21T11:55:00Z", "5 min ago"],
    ["2026-10-21T09:00:00Z", "3 h ago"],
    ["2026-10-19T12:00:00Z", "2 d ago"],
  ])("%s -> %s", (iso, label) => expect(timeAgo(iso, now)).toBe(label));
});

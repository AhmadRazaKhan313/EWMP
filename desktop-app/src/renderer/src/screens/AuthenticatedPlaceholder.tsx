import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LogOut, RefreshCw, LayoutDashboard, Umbrella, Bell, User, Wallet,
  CalendarDays, CalendarRange, ChevronsUpDown, PanelLeftClose, PanelLeft, Shield,
} from "lucide-react";
import { useAuthStore } from "../store/authStore";
import { useDeviceStore } from "../store/deviceStore";
import { useTimerStore } from "../store/timerStore";
import { getUnreadNotificationCount } from "../services/notificationsService";
import { cn, StatusDot } from "../components/ui";
import DashboardScreen from "./DashboardScreen";
import LeaveScreen from "./LeaveScreen";
import AttendanceScreen from "./AttendanceScreen";
import CalendarScreen from "./CalendarScreen";
import NotificationsScreen from "./NotificationsScreen";
import ProfileScreen from "./ProfileScreen";
import PayslipsScreen from "./PayslipsScreen";

type Tab = "dashboard" | "leave" | "attendance" | "calendar" | "payslips" | "notifications" | "profile";

const TABS: { id: Tab; label: string; icon: JSX.Element }[] = [
  { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={20} /> },
  { id: "leave", label: "Leave", icon: <Umbrella size={20} /> },
  { id: "attendance", label: "Attendance", icon: <CalendarDays size={20} /> },
  { id: "calendar", label: "Calendar", icon: <CalendarRange size={20} /> },
  { id: "payslips", label: "Payslips", icon: <Wallet size={20} /> },
  { id: "notifications", label: "Notifications", icon: <Bell size={20} /> },
  { id: "profile", label: "Profile", icon: <User size={20} /> },
];

/**
 * Authenticated shell.
 *
 * REDESIGNED to match the EWMP admin dashboard's chrome: a WHITE sidebar
 * rail with a bordered user chip at the top (name in indigo, live shift
 * status in orange underneath) and a red Sign out button pinned to the
 * bottom — not the dark-navy panel this used to render. See
 * styles/globals.css for why the whole app moved onto the admin's indigo
 * palette.
 *
 * Two structural changes beyond styling:
 *
 *  1. The per-screen page title/subtitle header is gone. Every screen now
 *     owns its own header, because each one needed a different right-hand
 *     action (New Request, Export, Mark all read) and a shared header bar
 *     had nowhere to put them.
 *
 *  2. The sidebar collapses to a 72px icon rail. The app's minimum window
 *     is 1024px wide but people do run it beside an IDE at half-screen;
 *     at that width a 238px rail eats a third of the content.
 */
export default function AuthenticatedPlaceholder(): JSX.Element {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const deviceStatus = useDeviceStore((s) => s.status);
  const retryEnrollment = useDeviceStore((s) => s.retryEnrollment);
  const timerStatus = useTimerStore((s) => s.status);
  const [tab, setTab] = useState<Tab>("dashboard");
  const [collapsed, setCollapsed] = useState(false);

  // Same 60s cadence as useNotificationBadge (tray badge) and the
  // dashboard's own pill — three surfaces reading one number, each
  // polling independently since TanStack Query dedupes by queryKey.
  const unreadQuery = useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: getUnreadNotificationCount,
    refetchInterval: 60_000,
  });
  const unreadCount = unreadQuery.data ?? 0;
  const initials =
    (user?.full_name ?? "")
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase())
      .join("") || "?";
  const needsDeviceAttention = deviceStatus === "needs_finish" || deviceStatus === "enrolling";

  // Shift status shown under the user's name, exactly where the admin UI
  // puts it. This is the one piece of live state visible from every
  // screen, so it stays in the chrome rather than only on the dashboard.
  const shiftLabel =
    timerStatus === "active" ? "Clocked In" : timerStatus === "on_break" ? "On Break" : "Clocked Out";
  const shiftTone =
    timerStatus === "active"
      ? "text-[hsl(var(--success))]"
      : timerStatus === "on_break"
        ? "text-[hsl(var(--warning))]"
        : "text-[hsl(var(--foreground-muted))]";

  // Shows the floating widget by default once signed in — fires once per
  // launch (empty deps), so toggling it off from the tray afterwards
  // sticks for the rest of the session instead of being fought back open.
  useEffect(() => {
    void window.ewmp.widget.isVisible().then((visible) => {
      if (!visible) void window.ewmp.widget.toggle();
    });
  }, []);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[hsl(var(--background))] text-[hsl(var(--foreground))]">
      <aside
        className={cn(
          "flex h-screen shrink-0 flex-col border-r border-[hsl(var(--sidebar-border))] bg-[hsl(var(--sidebar-background))] transition-[width] duration-200",
          collapsed ? "w-[76px] px-3" : "w-[256px] px-4",
        )}
      >
        {/* Brand — same lockup as the web app's sidebar. */}
        <div className={cn("flex items-center gap-2 pb-5 pt-5", collapsed && "justify-center")}>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[hsl(var(--sidebar-border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]">
            <Shield size={18} strokeWidth={2} className="text-[hsl(var(--primary))]" aria-hidden />
          </div>
          {!collapsed && (
            <span className="font-heading text-xl font-bold leading-8 tracking-tight text-[hsl(var(--foreground))]">
              EWMP
            </span>
          )}
        </div>

        <nav aria-label="Main" className="flex flex-col gap-1">
          {!collapsed && (
            <p className="mb-1 px-1 text-xs font-semibold uppercase leading-[18px] text-[hsl(var(--sidebar-muted))]">
              Menu
            </p>
          )}
          {TABS.map((t) => (
            <button
              key={t.id}
              data-testid={`nav-tab-${t.id}`}
              onClick={() => setTab(t.id)}
              title={collapsed ? t.label : undefined}
              aria-current={tab === t.id ? "page" : undefined}
              className={cn(
                "relative flex h-9 w-full items-center gap-3 rounded-md px-3 text-left text-sm font-semibold transition-colors",
                collapsed && "justify-center px-0",
                tab === t.id
                  ? "bg-[hsl(var(--sidebar-active))] text-[hsl(var(--sidebar-active-fg))]"
                  : "text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover))] hover:text-[hsl(var(--sidebar-active-fg))]",
              )}
            >
              <span className={cn("shrink-0", tab === t.id ? "text-[hsl(var(--primary))]" : "text-[hsl(var(--sidebar-muted))]")}>
                {t.icon}
              </span>
              {!collapsed && <span className="flex-1">{t.label}</span>}
              {t.id === "notifications" && unreadCount > 0 && !collapsed && (
                <span
                  data-testid="nav-unread-dot"
                  className="num inline-flex h-[22px] min-w-[22px] items-center justify-center rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--background))] px-1.5 text-xs font-medium text-[hsl(var(--sidebar-foreground))] shadow-[var(--shadow-xs)]"
                >
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
              {t.id === "notifications" && unreadCount > 0 && collapsed && (
                <span
                  data-testid="nav-unread-dot"
                  className="absolute right-2.5 top-2 h-2 w-2 rounded-full bg-[hsl(var(--warning))]"
                />
              )}
            </button>
          ))}
        </nav>

        <div className="mt-auto flex flex-col gap-1 pb-4 pt-3">
          {needsDeviceAttention && !collapsed && (
            <button
              onClick={() => void retryEnrollment()}
              disabled={deviceStatus === "enrolling"}
              data-testid="finish-device-setup-button"
              className="mb-1 flex items-center gap-2 rounded-md bg-[hsl(var(--status-warning-bg))] px-3 py-2.5 text-xs font-semibold text-[hsl(var(--status-warning-fg))] disabled:opacity-60"
            >
              <RefreshCw size={13} className={deviceStatus === "enrolling" ? "animate-spin" : ""} />
              {deviceStatus === "enrolling" ? "Finishing setup…" : "Finish device setup"}
            </button>
          )}

          <button
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn(
              "flex h-9 items-center gap-3 rounded-md px-3 text-sm font-semibold text-[hsl(var(--sidebar-foreground))] transition-colors hover:bg-[hsl(var(--sidebar-hover))]",
              collapsed && "justify-center px-0",
            )}
          >
            <span className="text-[hsl(var(--sidebar-muted))]">
              {collapsed ? <PanelLeft size={20} /> : <PanelLeftClose size={20} />}
            </span>
            {!collapsed && "Collapse"}
          </button>

          <button
            onClick={() => void logout()}
            data-testid="logout-button"
            title={collapsed ? "Sign out" : undefined}
            className={cn(
              "flex h-9 items-center gap-3 rounded-md px-3 text-sm font-semibold text-[hsl(var(--destructive))] transition-colors hover:bg-[hsl(var(--destructive-subtle))]",
              collapsed && "justify-center px-0",
            )}
          >
            <LogOut size={20} />
            {!collapsed && "Sign out"}
          </button>

          {/* Account card — the web sidebar's footer: avatar with a live
              status dot, name, shift status. */}
          <div
            className={cn(
              "mt-2 flex items-center gap-3 rounded-xl border border-[hsl(var(--sidebar-border))] bg-[hsl(var(--background))] p-3 shadow-[var(--shadow-xs)]",
              collapsed && "justify-center p-2",
            )}
          >
            <span className="relative shrink-0">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[hsl(var(--secondary))] text-sm font-semibold text-[hsl(var(--secondary-foreground))]">
                {initials}
              </span>
              <span
                aria-hidden
                className={cn(
                  "absolute bottom-0 right-0 h-3 w-3 rounded-full border-2 border-[hsl(var(--background))]",
                  timerStatus === "active"
                    ? "bg-[hsl(var(--success))]"
                    : timerStatus === "on_break"
                      ? "bg-[hsl(var(--warning))]"
                      : "bg-[hsl(var(--gray-400))]",
                )}
              />
            </span>
            {!collapsed && (
              <>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold leading-5 text-[hsl(var(--foreground))]">
                    {user?.full_name ?? "—"}
                  </span>
                  <span className={cn("flex items-center gap-1 text-xs leading-[18px]", shiftTone)}>
                    <StatusDot
                      color={timerStatus === "active" ? "green" : timerStatus === "on_break" ? "orange" : "gray"}
                      pulse={timerStatus === "active"}
                    />
                    {shiftLabel}
                  </span>
                </span>
                <ChevronsUpDown size={20} strokeWidth={1.75} aria-hidden className="shrink-0 text-[hsl(var(--gray-400))]" />
              </>
            )}
          </div>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        {tab === "dashboard" && <DashboardScreen onNavigate={setTab} />}
        {tab === "leave" && <LeaveScreen />}
        {tab === "attendance" && <AttendanceScreen />}
        {tab === "calendar" && <CalendarScreen onNavigate={setTab} />}
        {tab === "payslips" && <PayslipsScreen />}
        {tab === "notifications" && <NotificationsScreen />}
        {tab === "profile" && <ProfileScreen />}
      </main>
    </div>
  );
}

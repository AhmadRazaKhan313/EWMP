import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LogOut, RefreshCw, LayoutDashboard, Umbrella, Bell, User, Wallet,
  CalendarDays, CalendarRange, ChevronUp, ChevronDown, PanelLeftClose, PanelLeft,
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
  { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={19} /> },
  { id: "leave", label: "Leave", icon: <Umbrella size={19} /> },
  { id: "attendance", label: "Attendance", icon: <CalendarDays size={19} /> },
  { id: "calendar", label: "Calendar", icon: <CalendarRange size={19} /> },
  { id: "payslips", label: "Payslips", icon: <Wallet size={19} /> },
  { id: "notifications", label: "Notifications", icon: <Bell size={19} /> },
  { id: "profile", label: "Profile", icon: <User size={19} /> },
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
      ? "text-[hsl(var(--warning))]"
      : timerStatus === "on_break"
        ? "text-[hsl(var(--foreground-muted))]"
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
          "flex shrink-0 flex-col border-r border-[hsl(var(--sidebar-border))] bg-[hsl(var(--sidebar-background))] px-3 py-5 transition-[width] duration-200",
          collapsed ? "w-[72px]" : "w-[238px]",
        )}
      >
        {/* User chip — bordered card, name in indigo, live status beneath.
            Straight port of the admin sidebar's header. */}
        <div
          className={cn(
            "mb-6 flex items-center gap-2.5 rounded-xl border border-[hsl(var(--border))] p-2.5",
            collapsed && "justify-center px-1.5",
          )}
        >
          <span className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-full bg-[hsl(var(--primary))] font-heading text-xs font-semibold text-[hsl(var(--primary-foreground))]">
            {initials}
          </span>
          {!collapsed && (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold leading-tight text-[hsl(var(--primary))]">
                  {user?.full_name ?? "—"}
                </span>
                <span className={cn("flex items-center gap-1 text-xs font-medium", shiftTone)}>
                  <StatusDot
                    color={timerStatus === "active" ? "orange" : timerStatus === "on_break" ? "gray" : "gray"}
                    pulse={timerStatus === "active"}
                  />
                  {shiftLabel}
                </span>
              </span>
              <span className="flex shrink-0 flex-col text-[hsl(var(--foreground-muted))]">
                <ChevronUp size={11} />
                <ChevronDown size={11} />
              </span>
            </>
          )}
        </div>

        <nav className="flex flex-col gap-0.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              data-testid={`nav-tab-${t.id}`}
              onClick={() => setTab(t.id)}
              title={collapsed ? t.label : undefined}
              aria-current={tab === t.id ? "page" : undefined}
              className={cn(
                "flex items-center gap-3.5 rounded-[var(--radius-control)] px-2.5 py-2.5 text-left text-sm transition-colors",
                collapsed && "justify-center px-0",
                tab === t.id
                  ? "bg-[hsl(var(--sidebar-active-bg))] font-semibold text-[hsl(var(--sidebar-active-fg))]"
                  : "font-medium text-[hsl(var(--sidebar-muted))] hover:bg-[hsl(var(--sidebar-hover))] hover:text-[hsl(var(--sidebar-foreground))]",
              )}
            >
              <span className={tab === t.id ? "text-[hsl(var(--primary))]" : undefined}>{t.icon}</span>
              {!collapsed && <span className="flex-1">{t.label}</span>}
              {t.id === "notifications" && unreadCount > 0 && !collapsed && (
                <span
                  data-testid="nav-unread-dot"
                  className="num text-sm font-semibold text-[hsl(var(--warning))]"
                >
                  {unreadCount > 99 ? "99+" : String(unreadCount).padStart(2, "0")}
                </span>
              )}
              {t.id === "notifications" && unreadCount > 0 && collapsed && (
                <span
                  data-testid="nav-unread-dot"
                  className="absolute ml-5 -mt-4 h-2 w-2 rounded-full bg-[hsl(var(--warning))]"
                />
              )}
            </button>
          ))}
        </nav>

        <div className="mt-auto flex flex-col gap-2">
          {needsDeviceAttention && !collapsed && (
            <button
              onClick={() => void retryEnrollment()}
              disabled={deviceStatus === "enrolling"}
              data-testid="finish-device-setup-button"
              className="flex items-center gap-2 rounded-[var(--radius-control)] bg-[hsl(var(--status-warning-bg))] px-3 py-2.5 text-xs font-semibold text-[hsl(var(--status-warning-fg))] disabled:opacity-60"
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
              "flex items-center gap-3 rounded-[var(--radius-control)] px-2.5 py-2 text-sm font-medium text-[hsl(var(--sidebar-muted))] transition-colors hover:bg-[hsl(var(--sidebar-hover))] hover:text-[hsl(var(--sidebar-foreground))]",
              collapsed && "justify-center px-0",
            )}
          >
            {collapsed ? <PanelLeft size={18} /> : <PanelLeftClose size={18} />}
            {!collapsed && "Collapse"}
          </button>

          <button
            onClick={() => void logout()}
            data-testid="logout-button"
            title={collapsed ? "Sign out" : undefined}
            className={cn(
              "flex items-center justify-center gap-2.5 rounded-[var(--radius-control)] bg-[hsl(var(--destructive))] py-2.5 text-sm font-medium text-[hsl(var(--destructive-foreground))] transition-opacity hover:opacity-90",
              collapsed && "px-0",
            )}
          >
            <LogOut size={18} />
            {!collapsed && "Sign out"}
          </button>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        {tab === "dashboard" && <DashboardScreen onNavigate={setTab} />}
        {tab === "leave" && <LeaveScreen />}
        {tab === "attendance" && <AttendanceScreen />}
        {tab === "calendar" && <CalendarScreen />}
        {tab === "payslips" && <PayslipsScreen />}
        {tab === "notifications" && <NotificationsScreen />}
        {tab === "profile" && <ProfileScreen />}
      </main>
    </div>
  );
}

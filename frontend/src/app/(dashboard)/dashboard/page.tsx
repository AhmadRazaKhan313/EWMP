"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Users, UserCheck, Clock, TrendingUp,
  Monitor, Package, Ticket, ArrowUpRight,
  CalendarDays, LifeBuoy, Wallet, PlayCircle, Plane,
} from "lucide-react";
import apiClient from "@/services/api-client";
import { useAuthStore } from "@/store/auth.store";

// Stat card component
function StatCard({
  label,
  value,
  change,
  changeLabel,
  icon: Icon,
  trend = "up",
  isLoading,
}: {
  label: string;
  value: string | number;
  change?: string;
  changeLabel?: string;
  icon: React.ElementType;
  trend?: "up" | "down" | "neutral";
  isLoading?: boolean;
}) {
  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 shadow-[var(--shadow-xs)]">
      <div className="flex items-start justify-between">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]">
          <Icon size={17} className="text-[hsl(var(--foreground-subtle))]" />
        </div>
        {change && (
          <span
            className={`flex items-center gap-0.5 text-xs font-medium ${
              trend === "up"
                ? "text-[hsl(var(--success))]"
                : trend === "down"
                  ? "text-[hsl(var(--destructive))]"
                  : "text-[hsl(var(--foreground-muted))]"
            }`}
          >
            <ArrowUpRight size={12} />
            {change}
          </span>
        )}
      </div>
      <div className="mt-4">
        <p className="text-2xl font-semibold font-heading tracking-tight">
          {isLoading ? <span className="inline-block h-6 w-10 animate-pulse rounded bg-[hsl(var(--secondary))]" /> : value}
        </p>
        <p className="mt-0.5 text-sm text-[hsl(var(--foreground-muted))]">
          {label}
        </p>
        {changeLabel && (
          <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">
            {changeLabel}
          </p>
        )}
      </div>
    </div>
  );
}

// Quick action button
function QuickAction({
  label,
  description,
  icon: Icon,
  href,
}: {
  label: string;
  description: string;
  icon: React.ElementType;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-3.5 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4 shadow-[var(--shadow-xs)] transition-all hover:border-[hsl(var(--border-strong))] hover:shadow-[var(--shadow-sm)]"
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--secondary))] transition-colors group-hover:bg-[hsl(var(--primary))]">
        <Icon size={15} className="text-[hsl(var(--foreground-subtle))] group-hover:text-white" />
      </div>
      <div>
        <p className="text-sm font-medium">{label}</p>
        <p className="text-xs text-[hsl(var(--foreground-muted))]">{description}</p>
      </div>
    </Link>
  );
}

interface DashboardStats {
  total_employees: number;
  present_today: number;
  on_leave_today: number;
  open_tickets: number;
  devices_online: number;
  devices_total: number;
  assets_assigned: number;
}

function useDashboardStats(enabled: boolean) {
  return useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: async () => {
      const { data } = await apiClient.get<DashboardStats>("/dashboard/stats");
      return data;
    },
    // Skip the call entirely for a user with zero org-level view
    // permissions — every card that would use this data is hidden for
    // them anyway (see Dashboard's statCards filter), so there's nothing
    // to fetch.
    enabled,
    // Dashboard numbers are cheap to refetch and go stale fast (attendance,
    // ticket counts) — keep them reasonably fresh without polling.
    staleTime: 60_000,
  });
}

export default function DashboardPage() {
  // Bug fix, take 2: the previous version used one broad
  // hasAnyPermission("employees.view","payroll.view","assets.view") check
  // to decide "admin dashboard vs employee dashboard" — but that's wrong
  // for any role that has SOME narrow permission (e.g. an assets-only or
  // devices-only role has assets.view, so it tripped the OR and got the
  // full admin dashboard, Employees/Payroll cards included, even though
  // it has neither employees.view nor payroll.view). A binary split can't
  // represent this system's actual RBAC model, where permissions are
  // independent per-module.
  //
  // Fixed properly this time: every stat card and quick action checks its
  // OWN specific permission and only renders itself if the user actually
  // has it — see the `statCards` / `quickActions` filters inside
  // Dashboard() below. Nothing here is an all-or-nothing gate anymore.
  const { hasPermission, hasRole, user } = useAuthStore();

  // Mirrors the backend's owner-bypass (User.has_permission: "organization
  // owner ... always has full access to their own org") and the
  // platform-admin bypass — neither shows up as individual permission
  // codenames, so they need an explicit OR here rather than falling out
  // of the permission checks below on their own.
  const isFullAccess = !!user?.is_platform_admin || hasRole("owner");
  const can = (permission: string) => isFullAccess || hasPermission(permission);

  const orgVisibility = {
    employeesView: can("employees.view"),
    employeesCreate: can("employees.create"),
    attendanceOrgView: can("attendance.view"),
    leaveOrgView: can("leave.view"),
    payrollView: can("payroll.view"),
    payrollProcess: can("payroll.process"),
    devicesView: can("devices.view"),
    assetsView: can("assets.view"),
    assetsAssign: can("assets.assign"),
    helpdeskView: can("helpdesk.view"),
  };
  const hasAnyOrgVisibility = Object.values(orgVisibility).some(Boolean);

  return <Dashboard orgVisibility={orgVisibility} hasAnyOrgVisibility={hasAnyOrgVisibility} />;
}

interface OrgVisibility {
  employeesView: boolean;
  employeesCreate: boolean;
  attendanceOrgView: boolean;
  leaveOrgView: boolean;
  payrollView: boolean;
  payrollProcess: boolean;
  devicesView: boolean;
  assetsView: boolean;
  assetsAssign: boolean;
  helpdeskView: boolean;
}

function Dashboard({
  orgVisibility: v,
  hasAnyOrgVisibility,
}: {
  orgVisibility: OrgVisibility;
  hasAnyOrgVisibility: boolean;
}) {
  const user = useAuthStore((s) => s.user);
  const { data: stats, isLoading: statsLoading } = useDashboardStats(hasAnyOrgVisibility);
  const { data: activeSession, isLoading: sessionLoading } = useMyActiveSession();

  const attendanceRate =
    stats && stats.total_employees > 0
      ? Math.round((stats.present_today / stats.total_employees) * 100)
      : null;
  const devicesOnlinePercent =
    stats && stats.devices_total > 0
      ? Math.round((stats.devices_online / stats.devices_total) * 100)
      : null;

  // Each card/action only appears in this list if its own specific
  // permission is present — see the `can(...)` checks in orgVisibility.
  const statCards = [
    v.employeesView && (
      <StatCard key="employees" label="Total Employees" value={stats?.total_employees ?? 0}
        icon={Users} trend="neutral" isLoading={statsLoading} />
    ),
    (v.attendanceOrgView || v.leaveOrgView) && (
      <StatCard key="present" label="Present Today" value={stats?.present_today ?? 0}
        changeLabel={attendanceRate !== null ? `${attendanceRate}% attendance rate` : undefined}
        icon={UserCheck} trend="up" isLoading={statsLoading} />
    ),
    v.leaveOrgView && (
      <StatCard key="leave" label="On Leave" value={stats?.on_leave_today ?? 0}
        icon={Clock} trend="neutral" isLoading={statsLoading} />
    ),
    v.helpdeskView && (
      <StatCard key="tickets" label="Open Tickets" value={stats?.open_tickets ?? 0}
        icon={Ticket} trend="neutral" isLoading={statsLoading} />
    ),
    v.devicesView && (
      <StatCard key="devices" label="Devices Online" value={stats?.devices_online ?? 0}
        changeLabel={devicesOnlinePercent !== null ? `${devicesOnlinePercent}% of enrolled devices` : undefined}
        icon={Monitor} trend="up" isLoading={statsLoading} />
    ),
    v.assetsView && (
      <StatCard key="assets" label="Assets Assigned" value={stats?.assets_assigned ?? 0}
        icon={Package} trend="neutral" isLoading={statsLoading} />
    ),
  ].filter(Boolean);

  const quickActions = [
    v.employeesCreate && (
      <QuickAction key="add-employee" label="Add Employee" description="Onboard a new team member"
        icon={Users} href="/employees?new=1" />
    ),
    v.payrollProcess && (
      <QuickAction key="process-payroll" label="Process Payroll" description="Run payroll for this month"
        icon={TrendingUp} href="/payroll" />
    ),
    v.attendanceOrgView && (
      <QuickAction key="view-attendance" label="Team Attendance" description="Today's attendance report"
        icon={UserCheck} href="/attendance" />
    ),
    v.assetsAssign && (
      <QuickAction key="assign-asset" label="Assign Asset" description="Allocate equipment to employee"
        icon={Package} href="/assets" />
    ),
    // Always available — every authenticated user has these self-service
    // routes regardless of which (if any) management permissions they hold.
    <QuickAction key="my-attendance" label="My Attendance" description="View your check-in history"
      icon={CalendarDays} href="/attendance" />,
    <QuickAction key="apply-leave" label="Apply for Leave" description="Request time off"
      icon={Plane} href="/leave" />,
    <QuickAction key="my-payslips" label="My Payslips" description="View your salary history"
      icon={Wallet} href="/payroll" />,
    <QuickAction key="raise-ticket" label="Raise a Ticket" description="Get IT or HR support"
      icon={LifeBuoy} href="/helpdesk" />,
  ].filter(Boolean);

  const statusLabel = !activeSession
    ? "Not checked in yet"
    : activeSession.status === "on_break"
      ? "On break"
      : "Checked in";
  const statusTime = activeSession
    ? new Date(activeSession.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-heading text-xl font-semibold">
          Good morning, {user?.first_name ?? "there"} 👋
        </h2>
        <p className="mt-0.5 text-sm text-[hsl(var(--foreground-muted))]">
          {hasAnyOrgVisibility
            ? "Here's what's happening today."
            : "Here's your day at a glance."}
        </p>
      </div>

      {/* Personal status — every user has their own timer, regardless of
          any management permission. */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 shadow-[var(--shadow-xs)]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]">
              <PlayCircle size={17} className="text-[hsl(var(--foreground-subtle))]" />
            </div>
            <div>
              <p className="text-sm font-semibold">
                {sessionLoading ? (
                  <span className="inline-block h-4 w-28 animate-pulse rounded bg-[hsl(var(--secondary))]" />
                ) : (
                  statusLabel
                )}
              </p>
              {statusTime && (
                <p className="text-xs text-[hsl(var(--foreground-muted))]">Since {statusTime}</p>
              )}
            </div>
          </div>
          <Link href="/attendance"
            className="rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--secondary))]">
            View attendance
          </Link>
        </div>
      </div>

      {/* Org-wide stat cards — only the ones this user's permissions
          actually cover. Empty (no cards) for a plain self-service
          employee with no management permission at all. */}
      {statCards.length > 0 && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
          {statCards}
        </div>
      )}

      <div>
        <h3 className="mb-3 text-sm font-semibold text-[hsl(var(--foreground-subtle))] uppercase tracking-wide">
          Quick Actions
        </h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {quickActions}
        </div>
      </div>

      {/* Recent Activity surfaces other people's names/actions org-wide —
          keep it behind at least one management permission, never shown
          to a plain self-service employee. Still placeholder rows, not
          wired to real data — a separate, pre-existing gap (needs an
          aggregated activity/audit feed), not something this fix covers. */}
      {hasAnyOrgVisibility && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]">
          <div className="border-b border-[hsl(var(--border))] px-5 py-4">
            <h3 className="font-heading text-sm font-semibold">Recent Activity</h3>
          </div>
          <div className="divide-y divide-[hsl(var(--border))]">
            {[
              { action: "New employee onboarded", name: "Sarah Mitchell", time: "2 min ago" },
              { action: "Payroll approved", name: "November 2024", time: "1 hour ago" },
              { action: "Leave request submitted", name: "James Park", time: "2 hours ago" },
              { action: "Device enrolled", name: "LAPTOP-0094", time: "3 hours ago" },
              { action: "Ticket resolved", name: "VPN access issue", time: "4 hours ago" },
            ].map((item, i) => (
              <div key={i} className="flex items-center justify-between px-5 py-3.5">
                <div className="flex items-center gap-3">
                  <div className="h-2 w-2 rounded-full bg-[hsl(var(--success))]" />
                  <div>
                    <p className="text-sm font-medium">{item.action}</p>
                    <p className="text-xs text-[hsl(var(--foreground-muted))]">{item.name}</p>
                  </div>
                </div>
                <span className="text-xs text-[hsl(var(--foreground-muted))]">{item.time}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface ActiveWorkSession {
  id: string;
  started_at: string;
  status: "active" | "on_break" | "ended";
  total_minutes: number;
}

function useMyActiveSession() {
  return useQuery({
    queryKey: ["my-active-work-session"],
    queryFn: async () => {
      // GET /work-sessions/me/active — open to any authenticated user with
      // a linked Employee profile (see work_sessions.py). Returns null
      // when nothing is running, not a 404.
      const { data } = await apiClient.get<ActiveWorkSession | null>("/work-sessions/me/active");
      return data;
    },
    staleTime: 30_000,
  });
}
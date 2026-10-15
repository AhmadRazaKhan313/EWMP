"use client";

/**
 * Dashboard Overview.
 *
 * Layout follows the reference design:
 *   row 1  stat cards (4 across)
 *   row 2  Avg Work Hours area chart (2/3) + Work type statistics gauge (1/3)
 *   row 3  Last payroll statistics | Active leave requests | Recent activities
 *
 * Every widget is gated by its OWN permission (see `can(...)` below) and is
 * simply not rendered when the user lacks it. Nothing here is an
 * all-or-nothing admin/employee split — the RBAC model is per-module.
 *
 * Typography and spacing come from the design tokens (Untitled UI scale):
 * card titles text-lg/semibold, body text-sm, captions text-xs.
 */

import Link from "next/link";
import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { addDays, format, parseISO } from "date-fns";
import {
  Area, AreaChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  CalendarDays, Clock, LifeBuoy, Monitor, Package, PlayCircle, Plane,
  Ticket, TrendingUp, UserCheck, Users, Wallet,
} from "lucide-react";
import apiClient from "@/services/api-client";
import { useAuthStore } from "@/store/auth.store";
import { cn } from "@/utils/cn";

// ── Chart colours ────────────────────────────────────────────────────────────
// Recharts writes colours into SVG attributes, where CSS variables are not
// reliable, so these are the token values (blue-500, warning-500, success-500,
// brand-500, gray-400) as literals.
const C = {
  blue: "#2E90FA",
  orange: "#F79009",
  green: "#17B26A",
  purple: "#9E77ED",
  gray: "#A4A7AE",
} as const;

// ── Small shared pieces ──────────────────────────────────────────────────────

/** Card shell used by every widget. */
function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <section
      className={cn(
        "rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 shadow-[var(--shadow-xs)]",
        className,
      )}
    >
      {children}
    </section>
  );
}

function CardHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="font-heading text-base font-semibold leading-6 text-[hsl(var(--foreground))]">{title}</h3>
        {subtitle && <p className="text-sm text-[hsl(var(--foreground-muted))]">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[120px] items-center justify-center rounded-xl bg-[hsl(var(--background-subtle))] px-4 py-8 text-center text-sm text-[hsl(var(--foreground-muted))]">
      {children}
    </div>
  );
}

function Shimmer({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-md", className)} />;
}

const TONES = {
  blue: "bg-[hsl(var(--blue-50))] text-[hsl(var(--blue-600))]",
  orange: "bg-[hsl(var(--warning-50))] text-[hsl(var(--warning-600))]",
  green: "bg-[hsl(var(--success-50))] text-[hsl(var(--success-600))]",
  red: "bg-[hsl(var(--error-50))] text-[hsl(var(--error-600))]",
  purple: "bg-[hsl(var(--brand-50))] text-[hsl(var(--brand-600))]",
} as const;
type Tone = keyof typeof TONES;

function StatCard({
  label, value, hint, icon: Icon, tone, isLoading,
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon: React.ElementType;
  tone: Tone;
  isLoading?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 shadow-[var(--shadow-xs)]">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-[hsl(var(--foreground-muted))]">{label}</p>
        <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-xl", TONES[tone])}>
          <Icon size={20} aria-hidden />
        </span>
      </div>
      <div className="mt-1">
        {isLoading ? (
          <Shimmer className="h-8 w-16" />
        ) : (
          <p className="font-heading text-xl font-semibold text-[hsl(var(--foreground))]">{value}</p>
        )}
      </div>
      {hint && <p className="mt-2 text-xs text-[hsl(var(--foreground-muted))]">{hint}</p>}
    </div>
  );
}

function QuickAction({
  label, description, icon: Icon, href,
}: { label: string; description: string; icon: React.ElementType; href: string }) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-3.5 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 shadow-[var(--shadow-xs)] transition-all hover:border-[hsl(var(--brand-300))] hover:shadow-[var(--shadow-sm)]"
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--accent))] transition-colors group-hover:bg-[hsl(var(--primary))]">
        <Icon size={20} className="text-[hsl(var(--accent-foreground))] group-hover:text-white" />
      </div>
      <div>
        <p className="text-sm font-semibold text-[hsl(var(--foreground-subtle))]">{label}</p>
        <p className="text-sm text-[hsl(var(--foreground-muted))]">{description}</p>
      </div>
    </Link>
  );
}

function Initials({ name }: { name: string }) {
  const parts = name.trim().split(/\s+/);
  const text = `${parts[0]?.[0] ?? ""}${parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : ""}`.toUpperCase();
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--secondary))] text-sm font-semibold text-[hsl(var(--secondary-foreground))]">
      {text || "?"}
    </span>
  );
}

// ── Data ─────────────────────────────────────────────────────────────────────

interface DashboardStats {
  total_employees: number;
  present_today: number;
  on_leave_today: number;
  open_tickets: number;
  devices_online: number;
  devices_total: number;
  assets_assigned: number;
}

interface AttendanceItem {
  id: string;
  employee_id: string;
  employee_name: string;
  date: string;
  check_in: string | null;
  check_out: string | null;
  status: string;
  total_minutes: number | null;
}

interface LeaveItem {
  id: string;
  employee_name: string;
  leave_type: string;
  leave_type_color: string | null;
  start_date: string;
  end_date: string;
  status: string;
}

interface PayrollRun {
  id: string;
  name: string;
  period_start: string;
  period_end: string;
  status: string;
  total_gross: string;
  total_deductions: string;
  total_net: string;
  employee_count: number;
  currency: string;
}

/** yyyy-MM-dd in the browser's local time. */
const isoDay = (d: Date) => format(d, "yyyy-MM-dd");

function useDashboardStats(enabled: boolean) {
  return useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: async () => (await apiClient.get<DashboardStats>("/dashboard/stats")).data,
    enabled,
    staleTime: 60_000,
  });
}

function useAttendanceRange(from: string, to: string, enabled: boolean) {
  return useQuery({
    queryKey: ["dashboard-attendance", from, to],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: AttendanceItem[]; total: number }>("/attendance", {
        params: { date_from: from, date_to: to, page_size: 200 },
      });
      return data;
    },
    enabled,
    staleTime: 60_000,
  });
}

function useActiveLeave(enabled: boolean) {
  return useQuery({
    queryKey: ["dashboard-active-leave"],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: LeaveItem[] }>("/leave/requests", {
        params: { status: "approved", page_size: 200 },
      });
      return data.items;
    },
    enabled,
    staleTime: 60_000,
  });
}

function useLastPayrollRun(enabled: boolean) {
  return useQuery({
    queryKey: ["dashboard-last-payroll"],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: PayrollRun[] }>("/payroll/runs", { params: { page_size: 1 } });
      return data.items[0] ?? null;
    },
    enabled,
    staleTime: 5 * 60_000,
  });
}

const WORK_TYPES = [
  { key: "full_time", label: "Full time", color: C.orange },
  { key: "part_time", label: "Part time", color: C.blue },
  { key: "contract", label: "Contract", color: C.green },
  { key: "intern", label: "Intern", color: C.purple },
  { key: "freelance", label: "Freelance", color: C.gray },
] as const;

/** One cheap request per type (page_size=1), reading only `total`. */
function useWorkTypeCounts(enabled: boolean) {
  const results = useQueries({
    queries: WORK_TYPES.map((t) => ({
      queryKey: ["dashboard-work-type", t.key],
      queryFn: async () => {
        const { data } = await apiClient.get<{ total: number }>("/employees", {
          params: { employment_type: t.key, page_size: 1 },
        });
        return data.total;
      },
      enabled,
      staleTime: 5 * 60_000,
    })),
  });
  return {
    isLoading: results.some((r) => r.isLoading),
    data: WORK_TYPES.map((t, i) => ({ ...t, value: results[i]?.data ?? 0 })),
  };
}

// ── Widgets ──────────────────────────────────────────────────────────────────

function AvgWorkHours({ from, to, className }: { from: Date; to: Date; className?: string }) {
  const { data, isLoading } = useAttendanceRange(isoDay(from), isoDay(to), true);

  const series = useMemo(() => {
    const byDay = new Map<string, number[]>();
    for (const r of data?.items ?? []) {
      if (!r.total_minutes || r.total_minutes <= 0) continue;
      const list = byDay.get(r.date) ?? [];
      list.push(r.total_minutes / 60);
      byDay.set(r.date, list);
    }
    return Array.from({ length: 7 }, (_, i) => {
      const day = addDays(from, i);
      const hours = byDay.get(isoDay(day));
      const avg = hours && hours.length ? hours.reduce((a, b) => a + b, 0) / hours.length : 0;
      return { label: format(day, "EEE d"), hours: Math.round(avg * 10) / 10 };
    });
  }, [data, from]);

  const hasData = series.some((p) => p.hours > 0);

  return (
    <Card className={className}>
      <CardHeader
        title="Avg Work Hours"
        subtitle="Employee weekly average work hours"
        action={
          <span className="inline-flex h-9 shrink-0 items-center gap-2 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] px-3 text-sm font-medium text-[hsl(var(--foreground-subtle))] shadow-[var(--shadow-xs)]">
            <CalendarDays size={16} className="text-[hsl(var(--gray-400))]" aria-hidden />
            {format(from, "d MMM yyyy")} - {format(to, "d MMM yyyy")}
          </span>
        }
      />
      {isLoading ? (
        <Shimmer className="h-[260px] w-full" />
      ) : !hasData ? (
        <Empty>No attendance hours recorded for this week yet.</Empty>
      ) : (
        <div className="h-[260px] w-full text-[hsl(var(--foreground-muted))]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
              <defs>
                <linearGradient id="workHoursFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={C.orange} stopOpacity={0.28} />
                  <stop offset="100%" stopColor={C.orange} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="currentColor" strokeOpacity={0.12} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "currentColor", fontSize: 12 }} />
              <YAxis
                tickLine={false} axisLine={false} width={48}
                tick={{ fill: "currentColor", fontSize: 12 }}
                tickFormatter={(v: number) => `${v}h`}
                domain={[0, (max: number) => Math.max(8, Math.ceil(max))]}
              />
              <Tooltip
                cursor={{ stroke: C.orange, strokeOpacity: 0.3 }}
                content={({ active, payload, label }) =>
                  active && payload?.length ? (
                    <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-2 shadow-[var(--shadow-md)]">
                      <p className="text-xs text-[hsl(var(--foreground-muted))]">{label}</p>
                      <p className="text-sm font-semibold text-[hsl(var(--foreground))]">
                        {Number(payload[0]?.value).toFixed(1)} h
                      </p>
                    </div>
                  ) : null
                }
              />
              <Area
                type="monotone" dataKey="hours" stroke={C.orange} strokeWidth={2}
                fill="url(#workHoursFill)" dot={false}
                activeDot={{ r: 4, fill: "#fff", stroke: C.orange, strokeWidth: 2 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

function WorkTypeStats({ className }: { className?: string }) {
  const { data, isLoading } = useWorkTypeCounts(true);
  const total = data.reduce((a, d) => a + d.value, 0);
  const shown = data.filter((d) => d.value > 0);

  return (
    <Card className={className}>
      <CardHeader title="Work type statistics" subtitle="Employee count by work type" />
      {isLoading ? (
        <Shimmer className="h-[260px] w-full" />
      ) : total === 0 ? (
        <Empty>No employees yet.</Empty>
      ) : (
        <>
          <div className="relative mx-auto h-[190px] w-full max-w-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={shown} dataKey="value" nameKey="label"
                  startAngle={210} endAngle={-30}
                  innerRadius="72%" outerRadius="100%"
                  cornerRadius={8} paddingAngle={shown.length > 1 ? 4 : 0}
                  stroke="none" cy="55%"
                >
                  {shown.map((d) => <Cell key={d.key} fill={d.color} />)}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center pt-4">
              <span className="text-xs text-[hsl(var(--foreground-muted))]">Total employee</span>
              <span className="font-heading text-xl font-semibold text-[hsl(var(--foreground))]">{total}</span>
            </div>
          </div>
          <ul className="mt-2 flex flex-wrap justify-center gap-x-6 gap-y-3">
            {shown.map((d) => (
              <li key={d.key} className="flex items-start gap-2">
                <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: d.color }} aria-hidden />
                <span>
                  <span className="block text-sm font-semibold leading-5 text-[hsl(var(--foreground))]">{d.value}</span>
                  <span className="block text-xs text-[hsl(var(--foreground-muted))]">{d.label}</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

function money(amount: string | number, currency: string, compact = true) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return "-";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency", currency, notation: compact ? "compact" : "standard", maximumFractionDigits: 1,
    }).format(n);
  } catch {
    return `${currency} ${n.toLocaleString()}`;
  }
}

function PayrollBody({ run }: { run: PayrollRun }) {
  const net = Number(run.total_net) || 0;
  const ded = Number(run.total_deductions) || 0;
  const gross = Number(run.total_gross) || net + ded;
  const parts = [
    { key: "net", label: "Net salary", sub: "Paid out to employees", value: net, color: C.blue },
    { key: "ded", label: "Deductions", sub: "Includes taxes and contributions", value: ded, color: C.orange },
  ];

  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p className="text-sm text-[hsl(var(--foreground-muted))]">Payroll amount</p>
        <p className="font-heading text-xl font-semibold text-[hsl(var(--foreground))]">
          {money(gross, run.currency)}
        </p>
        <p className="text-xs text-[hsl(var(--foreground-muted))]">
          {run.employee_count} employees · {run.status.replace(/_/g, " ")}
        </p>
      </div>
      <div className="h-[110px] w-[110px] shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={gross > 0 ? parts : [{ key: "none", label: "", sub: "", value: 1, color: C.gray }]}
              dataKey="value" innerRadius="68%" outerRadius="100%"
              startAngle={90} endAngle={-270} cornerRadius={6}
              paddingAngle={gross > 0 ? 3 : 0} stroke="none"
            >
              {(gross > 0 ? parts : [{ key: "none", color: C.gray }]).map((p) => <Cell key={p.key} fill={p.color} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function PayrollLegend({ run }: { run: PayrollRun }) {
  const rows = [
    { label: "Net salary", sub: "Paid out to employees", value: run.total_net, color: C.blue },
    { label: "Deductions", sub: "Includes taxes and contributions", value: run.total_deductions, color: C.orange },
  ];
  return (
    <ul className="mt-5 space-y-3">
      {rows.map((r) => (
        <li key={r.label} className="flex items-start gap-2">
          <span className="mt-1 h-8 w-1 shrink-0 rounded-full" style={{ backgroundColor: r.color }} aria-hidden />
          <span>
            <span className="block text-sm font-semibold leading-5 text-[hsl(var(--foreground))]">
              {money(r.value, run.currency)}
            </span>
            <span className="block text-xs text-[hsl(var(--foreground-muted))]">{r.label} - {r.sub}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function LeaveBadge({ label, color }: { label: string; color: string | null }) {
  const valid = color && /^#[0-9a-f]{6}$/i.test(color) ? color : C.blue;
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-md px-2.5 py-1 text-xs font-medium"
      style={{ backgroundColor: `${valid}1A`, color: valid }}
    >
      {label}
    </span>
  );
}

function ActiveLeave({ className }: { className?: string }) {
  const { data, isLoading } = useActiveLeave(true);
  const today = isoDay(new Date());
  const active = (data ?? []).filter((l) => l.start_date <= today && l.end_date >= today);

  return (
    <Card className={className}>
      <CardHeader
        title={`Active leave request${isLoading ? "" : ` (${active.length})`}`}
        subtitle="Employees on leave today"
        action={
          <Link href="/leave" className="text-sm font-semibold text-[hsl(var(--primary))] hover:underline">
            View all
          </Link>
        }
      />
      {isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <Shimmer key={i} className="h-16 w-full" />)}</div>
      ) : active.length === 0 ? (
        <Empty>Nobody is on leave today.</Empty>
      ) : (
        <ul className="space-y-3">
          {active.slice(0, 4).map((l) => (
            <li key={l.id} className="flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] p-3">
              <Initials name={l.employee_name} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-[hsl(var(--foreground))]">{l.employee_name}</p>
                <p className="text-xs text-[hsl(var(--foreground-muted))]">
                  {format(parseISO(l.start_date), "d MMM")} - {format(parseISO(l.end_date), "d MMM yyyy")}
                </p>
              </div>
              <LeaveBadge label={l.leave_type} color={l.leave_type_color} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function RecentActivities({ className }: { className?: string }) {
  const today = isoDay(new Date());
  const { data, isLoading } = useAttendanceRange(today, today, true);
  const rows = useMemo(
    () =>
      (data?.items ?? [])
        .filter((r) => r.check_in)
        .sort((a, b) => (b.check_in ?? "").localeCompare(a.check_in ?? ""))
        .slice(0, 4),
    [data],
  );

  return (
    <Card className={className}>
      <CardHeader
        title="Recent Activities"
        subtitle={`Today - ${format(new Date(), "d MMMM yyyy")}`}
        action={
          <Link href="/attendance" className="text-sm font-semibold text-[hsl(var(--primary))] hover:underline">
            View all
          </Link>
        }
      />
      {isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <Shimmer key={i} className="h-16 w-full" />)}</div>
      ) : rows.length === 0 ? (
        <Empty>No check-ins yet today.</Empty>
      ) : (
        <ul className="space-y-3">
          {rows.map((r) => (
            <li key={r.id} className="flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] p-3">
              <Initials name={r.employee_name} />
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-[hsl(var(--foreground))]">
                  {r.employee_name} checked in
                </p>
                <p className="text-xs text-[hsl(var(--foreground-muted))]">
                  {format(new Date(r.check_in as string), "hh:mmaaa")}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

interface ActiveWorkSession {
  id: string;
  started_at: string;
  status: "active" | "on_break" | "ended";
  total_minutes: number;
}

function useMyActiveSession() {
  return useQuery({
    queryKey: ["my-active-work-session"],
    queryFn: async () => (await apiClient.get<ActiveWorkSession | null>("/work-sessions/me/active")).data,
    staleTime: 30_000,
  });
}

export default function DashboardPage() {
  const { hasPermission, hasRole, user } = useAuthStore();

  // Platform admins and the organisation owner have full access without
  // individual permission codenames (mirrors the backend's owner-bypass).
  const isFullAccess = !!user?.is_platform_admin || hasRole("owner");
  const can = (permission: string) => isFullAccess || hasPermission(permission);

  const v = {
    employeesView: can("employees.view"),
    employeesCreate: can("employees.create"),
    attendanceOrgView: can("attendance.view"),
    attendanceOwn: can("attendance.view") || can("attendance.view_own"),
    leaveOrgView: can("leave.view"),
    leaveAny: can("leave.view") || can("leave.apply"),
    payrollView: can("payroll.view"),
    payrollProcess: can("payroll.process"),
    devicesView: can("devices.view"),
    assetsView: can("assets.view"),
    assetsAssign: can("assets.assign"),
    helpdeskView: can("helpdesk.view"),
  };
  const hasAnyOrgVisibility =
    v.employeesView || v.attendanceOrgView || v.leaveOrgView || v.payrollView ||
    v.devicesView || v.assetsView || v.helpdeskView;

  const { data: stats, isLoading: statsLoading } = useDashboardStats(hasAnyOrgVisibility);
  const { data: activeSession, isLoading: sessionLoading } = useMyActiveSession();

  const attendanceRate =
    stats && stats.total_employees > 0 ? Math.round((stats.present_today / stats.total_employees) * 100) : null;
  const devicesPct =
    stats && stats.devices_total > 0 ? Math.round((stats.devices_online / stats.devices_total) * 100) : null;

  const statCards = [
    v.employeesView && (
      <StatCard key="employees" label="Total Employees" value={stats?.total_employees ?? 0}
        icon={Users} tone="blue" isLoading={statsLoading} />
    ),
    (v.attendanceOrgView || v.leaveOrgView) && (
      <StatCard key="present" label="Present Today" value={stats?.present_today ?? 0}
        hint={attendanceRate !== null ? `${attendanceRate}% attendance rate` : undefined}
        icon={UserCheck} tone="green" isLoading={statsLoading} />
    ),
    v.leaveOrgView && (
      <StatCard key="leave" label="On Leave" value={stats?.on_leave_today ?? 0}
        icon={Clock} tone="orange" isLoading={statsLoading} />
    ),
    v.helpdeskView && (
      <StatCard key="tickets" label="Open Tickets" value={stats?.open_tickets ?? 0}
        icon={Ticket} tone="red" isLoading={statsLoading} />
    ),
    v.devicesView && (
      <StatCard key="devices" label="Devices Online" value={stats?.devices_online ?? 0}
        hint={devicesPct !== null ? `${devicesPct}% of enrolled devices` : undefined}
        icon={Monitor} tone="purple" isLoading={statsLoading} />
    ),
    v.assetsView && (
      <StatCard key="assets" label="Assets Assigned" value={stats?.assets_assigned ?? 0}
        icon={Package} tone="blue" isLoading={statsLoading} />
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
    <QuickAction key="my-attendance" label="My Attendance" description="View your check-in history"
      icon={CalendarDays} href="/attendance" />,
    <QuickAction key="apply-leave" label="Apply for Leave" description="Request time off"
      icon={Plane} href="/leave" />,
    <QuickAction key="my-payslips" label="My Payslips" description="View your salary history"
      icon={Wallet} href="/payroll" />,
    <QuickAction key="raise-ticket" label="Raise a Ticket" description="Get IT or HR support"
      icon={LifeBuoy} href="/helpdesk" />,
  ].filter(Boolean);

  const statusLabel = !activeSession ? "Not checked in" : activeSession.status === "on_break" ? "On break" : "Checked in";
  const statusTime = activeSession
    ? new Date(activeSession.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;

  // Last 7 days ending today, same window for the chart and its label.
  const to = useMemo(() => new Date(), []);
  const from = useMemo(() => addDays(to, -6), [to]);

  const showWorkHours = v.attendanceOwn;
  const showWorkType = v.employeesView;
  const rowTwoCols = showWorkHours && showWorkType ? "lg:grid-cols-3" : "lg:grid-cols-1";
  const rowThree = [v.payrollView, v.leaveAny, v.attendanceOrgView].filter(Boolean).length;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-heading text-xl font-semibold text-[hsl(var(--foreground))]">
            Dashboard Overview
          </h2>
          <p className="mt-1 text-sm text-[hsl(var(--foreground-muted))]">
            Welcome back, {user?.first_name ?? "there"} · {format(new Date(), "EEEE do MMMM yyyy")}
          </p>
        </div>
        <Link
          href="/attendance"
          className="flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] py-2 pl-3 pr-4 shadow-[var(--shadow-xs)] transition-colors hover:bg-[hsl(var(--background-subtle))]"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--accent))]">
            <PlayCircle size={18} className="text-[hsl(var(--accent-foreground))]" aria-hidden />
          </span>
          <span>
            <span className="block text-sm font-semibold leading-5 text-[hsl(var(--foreground-subtle))]">
              {sessionLoading ? <Shimmer className="h-4 w-24" /> : statusLabel}
            </span>
            <span className="block text-xs text-[hsl(var(--foreground-muted))]">
              {statusTime ? `Since ${statusTime}` : "View attendance"}
            </span>
          </span>
        </Link>
      </div>

      {statCards.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">{statCards}</div>
      )}

      {(showWorkHours || showWorkType) && (
        <div className={cn("grid grid-cols-1 gap-4", rowTwoCols)}>
          {showWorkHours && <AvgWorkHours from={from} to={to} className={showWorkType ? "lg:col-span-2" : undefined} />}
          {showWorkType && <WorkTypeStats />}
        </div>
      )}

      {rowThree > 0 && (
        <div
          className={cn(
            "grid grid-cols-1 gap-4",
            rowThree >= 3 ? "lg:grid-cols-3" : rowThree === 2 ? "lg:grid-cols-2" : "lg:grid-cols-1",
          )}
        >
          {v.payrollView && <LastPayrollCard />}
          {v.leaveAny && <ActiveLeave />}
          {v.attendanceOrgView && <RecentActivities />}
        </div>
      )}

      <div>
        <h3 className="mb-4 font-heading text-base font-semibold leading-6 text-[hsl(var(--foreground))]">
          Quick Actions
        </h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">{quickActions}</div>
      </div>
    </div>
  );
}

/** Payroll card with the legend underneath the donut (matches the reference). */
function LastPayrollCard() {
  const { data: run, isLoading } = useLastPayrollRun(true);
  return (
    <Card>
      <CardHeader
        title="Last payroll statistics"
        subtitle={
          run
            ? `${format(parseISO(run.period_start), "d MMM")} - ${format(parseISO(run.period_end), "d MMM yyyy")}`
            : undefined
        }
        action={
          <Link href="/payroll" className="text-sm font-semibold text-[hsl(var(--primary))] hover:underline">
            View
          </Link>
        }
      />
      {isLoading ? (
        <Shimmer className="h-[220px] w-full" />
      ) : !run ? (
        <Empty>No payroll has been run yet.</Empty>
      ) : (
        <>
          <PayrollBody run={run} />
          <PayrollLegend run={run} />
        </>
      )}
    </Card>
  );
}
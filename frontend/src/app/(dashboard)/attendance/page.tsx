"use client";

import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { CalendarDays, UserCheck, UserX, Coffee, Hourglass, Sun } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Card, EmptyState, PageHeader } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { CheckInWidget } from "./CheckInWidget";

interface MyWorkSession {
  id: string;
  started_at: string;
  ended_at: string | null;
  status: "active" | "on_break" | "ended";
  total_minutes: number | null;
}

function formatDateTime(dt: string | null) {
  if (!dt) return "—";
  return new Date(dt).toLocaleString("en-US", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

const myStatusConfig: Record<string, { label: string; variant: "success" | "warning" | "default" }> = {
  active:    { label: "Checked In", variant: "success" },
  on_break:  { label: "On Break",   variant: "warning" },
  ended:     { label: "Ended",      variant: "default" },
};

const myColumns: ColumnDef<MyWorkSession, unknown>[] = [
  {
    header: "Check In",
    accessorKey: "started_at",
    cell: ({ getValue }) => (
      <span className="font-mono text-sm">{formatDateTime(getValue<string>())}</span>
    ),
  },
  {
    header: "Check Out",
    accessorKey: "ended_at",
    cell: ({ getValue }) => (
      <span className="font-mono text-sm text-[hsl(var(--foreground-subtle))]">
        {formatDateTime(getValue<string | null>())}
      </span>
    ),
  },
  {
    header: "Duration",
    accessorKey: "total_minutes",
    cell: ({ getValue }) => {
      const m = getValue<number | null>();
      if (m == null) return <span className="text-[hsl(var(--foreground-muted))]">—</span>;
      return <span className="text-sm">{Math.floor(m / 60)}h {m % 60}m</span>;
    },
  },
  {
    header: "Status",
    accessorKey: "status",
    cell: ({ getValue }) => {
      const s = getValue<string>();
      const cfg = myStatusConfig[s] ?? { label: s, variant: "default" as const };
      return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
    },
  },
];

// Every logged-in employee's own check-in history — sourced from
// /work-sessions/me, which needs no special permission (unlike the
// org-wide /attendance list below, which requires attendance.view and is
// meant for HR/managers). This is what makes sure an employee always sees
// their own attendance regardless of role.
function MySessionsTable() {
  const { data, isLoading } = useQuery({
    queryKey: ["work-session", "history"],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: MyWorkSession[]; total: number }>("/work-sessions/me", {
        params: { page: 1, page_size: 10 },
      });
      return data;
    },
    refetchInterval: 15000,
  });

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">My Attendance</h3>
      <DataTable
        data={data?.items ?? []}
        columns={myColumns}
        isLoading={isLoading}
        searchPlaceholder=""
        emptyState={
          <EmptyState
            icon={CalendarDays}
            title="No check-ins yet"
            description="Your check-in history will show up here once you check in — from the web or the desktop app."
          />
        }
      />
    </div>
  );
}

// ── Daily sheet ───────────────────────────────────────────────────────────────
// One row per employee who was employed on the chosen day, with a status derived
// on the server from their shift, the holiday calendar, approved leave and real
// check-ins/outs (GET /attendance/daily). Employees who did not check in appear
// here too, which is what makes "Absent" possible.

type DayStatus =
  | "present" | "late" | "half_day" | "work_from_home" | "missed_punch"
  | "absent" | "on_leave" | "holiday" | "weekly_off"
  | "not_checked_in" | "scheduled";

interface DailyRow {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  department_name: string | null;
  shift_name: string | null;
  shift_start: string | null;
  shift_end: string | null;
  status: DayStatus;
  check_in: string | null;
  check_out: string | null;
  total_minutes: number | null;
  late_minutes: number | null;
  overtime_minutes: number | null;
  is_regularized: boolean;
  detail: string | null;
}

interface DailySummary extends Record<DayStatus, number> {
  present_total: number;
  expected: number;
  total: number;
}

interface DailyResponse {
  date: string;
  items: DailyRow[];
  summary: DailySummary;
  total: number;
  total_pages: number;
}

const statusConfig: Record<DayStatus, { label: string; variant: "success" | "warning" | "error" | "default" | "info" }> = {
  present:        { label: "Present",        variant: "success" },
  late:           { label: "Late",           variant: "warning" },
  half_day:       { label: "Half Day",       variant: "warning" },
  work_from_home: { label: "WFH",            variant: "info" },
  missed_punch:   { label: "Missed punch",   variant: "warning" },
  absent:         { label: "Absent",         variant: "error" },
  on_leave:       { label: "On Leave",       variant: "info" },
  holiday:        { label: "Holiday",        variant: "default" },
  weekly_off:     { label: "Weekly off",     variant: "default" },
  not_checked_in: { label: "Not checked in", variant: "warning" },
  scheduled:      { label: "Scheduled",      variant: "default" },
};

// Each filter is a group of statuses sent to the server as a comma list.
const FILTERS = [
  { key: "all",     label: "All",            statuses: "" },
  { key: "present", label: "Present",        statuses: "present,late,half_day,work_from_home,missed_punch" },
  { key: "late",    label: "Late",           statuses: "late" },
  { key: "absent",  label: "Absent",         statuses: "absent" },
  { key: "leave",   label: "On leave",       statuses: "on_leave" },
  { key: "pending", label: "Not checked in", statuses: "not_checked_in,scheduled" },
  { key: "off",     label: "Off",            statuses: "holiday,weekly_off" },
] as const;
type FilterKey = (typeof FILTERS)[number]["key"];

function formatTime(dt: string | null) {
  if (!dt) return "—";
  return new Date(dt).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function formatDuration(minutes: number | null) {
  if (!minutes) return "—";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}h ${m}m`;
}

const columns: ColumnDef<DailyRow, unknown>[] = [
  {
    header: "Employee",
    accessorKey: "employee_name",
    cell: ({ row }) => (
      <div>
        <p className="text-sm font-medium">{row.original.employee_name}</p>
        <p className="text-xs text-[hsl(var(--foreground-muted))]">
          {row.original.employee_code}
          {row.original.department_name ? ` · ${row.original.department_name}` : ""}
        </p>
      </div>
    ),
  },
  {
    header: "Shift",
    accessorKey: "shift_name",
    cell: ({ row }) =>
      row.original.shift_name ? (
        <div>
          <p className="text-sm">{row.original.shift_name}</p>
          <p className="font-mono text-xs text-[hsl(var(--foreground-muted))]">
            {row.original.shift_start}–{row.original.shift_end}
          </p>
        </div>
      ) : (
        <span className="text-[hsl(var(--foreground-muted))]">—</span>
      ),
  },
  {
    header: "Status",
    accessorKey: "status",
    cell: ({ row }) => {
      const cfg = statusConfig[row.original.status] ?? { label: row.original.status, variant: "default" as const };
      return (
        <span title={row.original.detail ?? undefined}>
          <Badge variant={cfg.variant}>{cfg.label}</Badge>
        </span>
      );
    },
  },
  {
    header: "Check In",
    accessorKey: "check_in",
    cell: ({ getValue }) => (
      <span className="font-mono text-sm text-[hsl(var(--foreground-subtle))]">{formatTime(getValue<string | null>())}</span>
    ),
  },
  {
    header: "Check Out",
    accessorKey: "check_out",
    cell: ({ getValue }) => (
      <span className="font-mono text-sm text-[hsl(var(--foreground-subtle))]">{formatTime(getValue<string | null>())}</span>
    ),
  },
  {
    header: "Late By",
    accessorKey: "late_minutes",
    cell: ({ getValue }) => {
      const m = getValue<number | null>();
      if (!m) return <span className="text-[hsl(var(--foreground-muted))]">—</span>;
      return <span className="text-sm text-[hsl(var(--warning))]">{formatDuration(m)}</span>;
    },
  },
  {
    header: "Worked",
    accessorKey: "total_minutes",
    cell: ({ getValue }) => (
      <span className="text-sm text-[hsl(var(--foreground-subtle))]">{formatDuration(getValue<number | null>())}</span>
    ),
  },
  {
    header: "Overtime",
    accessorKey: "overtime_minutes",
    cell: ({ getValue }) => {
      const m = getValue<number | null>();
      if (!m) return <span className="text-[hsl(var(--foreground-muted))]">—</span>;
      return <span className="text-sm text-[hsl(var(--success))]">+{formatDuration(m)}</span>;
    },
  },
];

function SummaryCard({
  icon: Icon, label, value, hint, color, active, onClick,
}: {
  icon: React.ElementType; label: string; value: number | string; hint?: string; color: string;
  active?: boolean; onClick?: () => void;
}) {
  return (
    <button type="button" onClick={onClick} className="text-left">
      <Card className={active ? "ring-2 ring-[hsl(var(--ring))]" : undefined}>
        <div className="flex items-center gap-3">
          <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${color}`}>
            <Icon size={16} className="text-white" />
          </div>
          <div>
            <p className="text-xl font-semibold font-heading">{value}</p>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">
              {label}
              {hint ? ` · ${hint}` : ""}
            </p>
          </div>
        </div>
      </Card>
    </button>
  );
}

export default function AttendancePage() {
  // null = "today", decided by the server in the ORGANISATION's timezone (the
  // browser's own date can be a different day).
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const [pageIndex, setPageIndex] = useState(0);
  const hasEmployeeProfile = useAuthStore((s) => s.user?.has_employee_profile);

  const statuses = FILTERS.find((f) => f.key === filter)?.statuses ?? "";

  const { data, isLoading } = useQuery({
    queryKey: ["attendance-daily", selectedDate, statuses, search, pageIndex],
    queryFn: async () => {
      const { data } = await apiClient.get<DailyResponse>("/attendance/daily", {
        params: {
          ...(selectedDate ? { date: selectedDate } : {}),
          ...(statuses ? { status: statuses } : {}),
          ...(search ? { search } : {}),
          page: pageIndex + 1,
          page_size: 25,
        },
      });
      return data;
    },
    placeholderData: (prev) => prev,
    refetchInterval: 60_000, // a check-in from the desktop app shows up within a minute
  });

  const s = data?.summary;
  const pick = (key: FilterKey) => {
    setFilter(key);
    setPageIndex(0);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance"
        description="Who is present, absent, late or off — worked out from each person's shift, holidays, leave and check-ins."
        action={
          <input
            type="date"
            value={selectedDate ?? data?.date ?? ""}
            onChange={(e) => {
              setSelectedDate(e.target.value || null);
              setPageIndex(0);
            }}
            className="h-9 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm outline-none focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]"
          />
        }
      />

      {/* Self check-in/out and "my attendance" are only meaningful for a
          user who is also an Employee (has a linked Employee profile) —
          a pure admin/owner account with no Employee record has nothing
          to check in as, and the backend 404s ("No employee profile is
          linked to this user") on every call these two make. */}
      {hasEmployeeProfile && (
        <>
          <CheckInWidget />
          <MySessionsTable />
        </>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <SummaryCard icon={UserCheck} label="Present" value={s?.present_total ?? 0}
          hint={s ? `${s.late} late` : undefined} color="bg-[hsl(var(--success))]"
          active={filter === "present"} onClick={() => pick("present")} />
        <SummaryCard icon={UserX} label="Absent" value={s?.absent ?? 0} color="bg-[hsl(var(--destructive))]"
          active={filter === "absent"} onClick={() => pick("absent")} />
        <SummaryCard icon={Coffee} label="On Leave" value={s?.on_leave ?? 0} color="bg-[hsl(var(--info))]"
          active={filter === "leave"} onClick={() => pick("leave")} />
        <SummaryCard icon={Hourglass} label="Not checked in" value={(s?.not_checked_in ?? 0) + (s?.scheduled ?? 0)}
          color="bg-[hsl(var(--warning))]" active={filter === "pending"} onClick={() => pick("pending")} />
        <SummaryCard icon={Sun} label="Off" value={(s?.holiday ?? 0) + (s?.weekly_off ?? 0)} color="bg-[hsl(var(--foreground-muted))]"
          active={filter === "off"} onClick={() => pick("off")} />
      </div>

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => pick(f.key)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              filter === f.key
                ? "border-transparent bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                : "border-[hsl(var(--border))] text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--muted))]"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <DataTable
        data={data?.items ?? []}
        columns={columns}
        isLoading={isLoading}
        searchPlaceholder="Search by name, code or email…"
        manual={{
          pageIndex,
          pageCount: data?.total_pages ?? 1,
          totalRows: data?.total ?? 0,
          onPageChange: setPageIndex,
          searchValue: search,
          onSearchChange: (v) => {
            setSearch(v);
            setPageIndex(0);
          },
        }}
        emptyState={
          <EmptyState
            icon={CalendarDays}
            title="No employees to show"
            description="Nobody matches this date and filter. Employees appear on the days they were employed."
          />
        }
      />
    </div>
  );
}

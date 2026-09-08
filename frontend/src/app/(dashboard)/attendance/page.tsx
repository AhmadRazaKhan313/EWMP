"use client";

import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { CalendarDays, Clock, UserCheck, UserX, Coffee } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Card, EmptyState, PageHeader } from "@/components/atoms";
import type { AttendanceRecord } from "@/types";
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

const statusConfig: Record<string, { label: string; variant: "success" | "warning" | "error" | "default" | "info" }> = {
  present:        { label: "Present",        variant: "success" },
  absent:         { label: "Absent",         variant: "error" },
  late:           { label: "Late",           variant: "warning" },
  half_day:       { label: "Half Day",       variant: "warning" },
  on_leave:       { label: "On Leave",       variant: "info" },
  holiday:        { label: "Holiday",        variant: "default" },
  weekend:        { label: "Weekend",        variant: "default" },
  work_from_home: { label: "WFH",           variant: "info" },
};

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

const columns: ColumnDef<AttendanceRecord, unknown>[] = [
  {
    header: "Date",
    accessorKey: "date",
    cell: ({ getValue }) => (
      <span className="text-sm font-medium">
        {new Date(getValue<string>()).toLocaleDateString("en-US", {
          weekday: "short", day: "numeric", month: "short",
        })}
      </span>
    ),
  },
  {
    header: "Status",
    accessorKey: "status",
    cell: ({ getValue }) => {
      const s = getValue<string>();
      const cfg = statusConfig[s] ?? { label: s, variant: "default" as const };
      return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
    },
  },
  {
    header: "Check In",
    accessorKey: "check_in",
    cell: ({ getValue }) => (
      <span className="font-mono text-sm text-[hsl(var(--foreground-subtle))]">
        {formatTime(getValue<string | null>())}
      </span>
    ),
  },
  {
    header: "Check Out",
    accessorKey: "check_out",
    cell: ({ getValue }) => (
      <span className="font-mono text-sm text-[hsl(var(--foreground-subtle))]">
        {formatTime(getValue<string | null>())}
      </span>
    ),
  },
  {
    header: "Duration",
    accessorKey: "total_minutes",
    cell: ({ getValue }) => (
      <span className="text-sm text-[hsl(var(--foreground-subtle))]">
        {formatDuration(getValue<number | null>())}
      </span>
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
  {
    header: "Late By",
    accessorKey: "late_minutes",
    cell: ({ getValue }) => {
      const m = getValue<number | null>();
      if (!m) return <span className="text-[hsl(var(--foreground-muted))]">—</span>;
      return <span className="text-sm text-[hsl(var(--warning))]">{formatDuration(m)}</span>;
    },
  },
];

function StatCard({ icon: Icon, label, value, color }: { icon: React.ElementType; label: string; value: number | string; color: string }) {
  return (
    <Card>
      <div className="flex items-center gap-3">
        <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${color}`}>
          <Icon size={16} className="text-white" />
        </div>
        <div>
          <p className="text-xl font-semibold font-heading">{value}</p>
          <p className="text-xs text-[hsl(var(--foreground-muted))]">{label}</p>
        </div>
      </div>
    </Card>
  );
}

export default function AttendancePage() {
  const today = new Date().toISOString().split("T")[0];
  const [selectedDate, setSelectedDate] = useState(today);
  const hasEmployeeProfile = useAuthStore((s) => s.user?.has_employee_profile);

  const { data, isLoading } = useQuery({
    queryKey: ["attendance", selectedDate],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: AttendanceRecord[]; total: number }>("/attendance", {
        params: { date: selectedDate },
      });
      return data;
    },
  });

  const records = data?.items ?? [];
  const present  = records.filter((r) => r.status === "present").length;
  const absent   = records.filter((r) => r.status === "absent").length;
  const late     = records.filter((r) => r.status === "late").length;
  const onLeave  = records.filter((r) => r.status === "on_leave").length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance"
        description="Track daily attendance, check-in/out times, and work duration."
        action={
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="h-9 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
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

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard icon={UserCheck} label="Present"  value={present}  color="bg-[hsl(var(--success))]" />
        <StatCard icon={UserX}     label="Absent"   value={absent}   color="bg-[hsl(var(--destructive))]" />
        <StatCard icon={Clock}     label="Late"     value={late}     color="bg-[hsl(var(--warning))]" />
        <StatCard icon={Coffee}    label="On Leave" value={onLeave}  color="bg-[hsl(var(--info))]" />
      </div>

      <DataTable
        data={records}
        columns={columns}
        isLoading={isLoading}
        searchPlaceholder="Search by employee…"
        emptyState={
          <EmptyState
            icon={CalendarDays}
            title="No attendance records"
            description="No attendance data found for the selected date."
          />
        }
      />
    </div>
  );
}
"use client";

import { CalendarDays } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "@/services/api-client";
import { Card } from "@/components/atoms";
import { AttendanceStatusBadge } from "./AttendanceStatusBadge";

interface Item {
  id: string;
  date: string;
  status: string;
  check_in: string | null;
  check_out: string | null;
  marked_by_admin?: boolean;
}

const time = (dt: string | null) =>
  dt ? new Date(dt).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }) : "—";

/** The employee's last 7 recorded days, for the profile page (needs attendance.view). */
export function RecentAttendanceCard({ employeeId }: { employeeId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["attendance", "employee", employeeId],
    queryFn: async () =>
      (await apiClient.get<{ items: Item[] }>("/attendance", { params: { employee_id: employeeId, page_size: 7 } })).data.items,
  });

  return (
    <Card padding={false}>
      <div className="flex items-center gap-2 border-b border-[hsl(var(--border))] px-5 py-4">
        <CalendarDays size={15} className="text-[hsl(var(--foreground-subtle))]" />
        <h3 className="font-heading text-sm font-semibold">Recent Attendance</h3>
      </div>
      <div className="px-5 py-2" data-testid="recent-attendance">
        {isLoading && <p className="py-3 text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>}
        {!isLoading && !data?.length && (
          <p className="py-3 text-sm text-[hsl(var(--foreground-muted))]">No attendance recorded yet.</p>
        )}
        {data?.map((r) => (
          <div key={r.id} className="flex items-center justify-between border-b border-[hsl(var(--border))] py-2.5 text-sm last:border-0">
            <span className="w-28 font-medium">{r.date}</span>
            <AttendanceStatusBadge status={r.status} />
            <span className="font-mono text-xs text-[hsl(var(--foreground-subtle))]">
              {time(r.check_in)} – {time(r.check_out)}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

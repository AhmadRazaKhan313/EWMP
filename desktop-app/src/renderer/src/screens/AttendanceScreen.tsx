import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { getMyAttendance } from "../services/attendanceService";
import { listShifts, pickDefaultShift, dailyHoursForShift } from "../services/shiftsService";
import type { AttendanceStatus } from "../types/hrms";
import { formatDate, formatHours, formatMonthYear, formatShortTime } from "../lib/format";
import {
  Badge, Button, Card, EmptyState, ErrorState, ProgressBar, SkeletonList, StatBand, cn,
} from "../components/ui";

/**
 * Attendance — the employee's own month, read-only.
 *
 * REBUILT from a flat "last 30 records" card list into a month view with
 * a summary band and a proper table. Two real fixes underneath the
 * restyle:
 *
 *  1. It now asks for a DATE RANGE (attendanceService.getMyAttendance with a date range)
 *     instead of page 1 / 30 rows. The old version silently truncated —
 *     anyone with more than 30 records simply could not scroll back, and
 *     the list mixed two months with no visual break.
 *
 *  2. Each row carries a progress bar against the shift's expected hours,
 *     split worked / overtime. A short day is now visible before any
 *     number is read.
 *
 * Still deliberately read-only: no regularization form. Requesting a
 * correction is an `attendance.regularize` flow that does not exist on
 * this backend yet — see the note at the bottom of the file.
 */

const STATUS_LABEL: Record<AttendanceStatus, string> = {
  present: "Present",
  absent: "Absent",
  late: "Late",
  half_day: "Half day",
  on_leave: "On leave",
  holiday: "Holiday",
  weekend: "Weekend",
  work_from_home: "Work from home",
};

// Orange means waiting/attention, red means wrong — see globals.css.
const STATUS_VARIANT: Record<AttendanceStatus, "success" | "warning" | "error" | "info" | "default"> = {
  present: "success",
  work_from_home: "success",
  late: "warning",
  half_day: "warning",
  absent: "error",
  on_leave: "info",
  holiday: "default",
  weekend: "default",
};

export default function AttendanceScreen(): JSX.Element {
  const [monthOffset, setMonthOffset] = useState(0);
  const month = useMemo(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth() + monthOffset, 1);
  }, [monthOffset]);
  const monthKey = `${month.getFullYear()}-${month.getMonth()}`;

  const attendanceQuery = useQuery({
    queryKey: ["attendance", "month", monthKey],
    queryFn: () =>
      getMyAttendance({
        from: new Date(month.getFullYear(), month.getMonth(), 1),
        to: new Date(month.getFullYear(), month.getMonth() + 1, 0),
      }),
  });
  const shiftsQuery = useQuery({ queryKey: ["shifts"], queryFn: listShifts, staleTime: 60 * 60 * 1000 });
  const expectedMinutes = dailyHoursForShift(pickDefaultShift(shiftsQuery.data)) * 60;

  const records = attendanceQuery.data ?? [];
  const worked = records.reduce((s, r) => s + (r.total_minutes ?? 0), 0);
  const overtime = records.reduce((s, r) => s + (r.overtime_minutes ?? 0), 0);
  const late = records.reduce((s, r) => s + (r.late_minutes ?? 0), 0);
  const present = records.filter((r) => ["present", "late", "work_from_home", "half_day"].includes(r.status)).length;

  return (
    <div className="flex w-full flex-col gap-[18px] p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-[22px] font-semibold tracking-tight text-[hsl(var(--foreground))]">
            Attendance
          </h1>
          <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
            Your own check-in and check-out history
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setMonthOffset((o) => o - 1)}
            aria-label="Previous month"
          >
            <ChevronLeft size={15} />
          </Button>
          <span className="min-w-[150px] text-center text-sm font-semibold text-[hsl(var(--foreground))]">
            {formatMonthYear(month)}
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setMonthOffset((o) => Math.min(0, o + 1))}
            disabled={monthOffset >= 0}
            aria-label="Next month"
          >
            <ChevronRight size={15} />
          </Button>
        </div>
      </header>

      <StatBand
        items={[
          { label: "Days present", value: String(present) },
          { label: "Hours worked", value: formatHours(worked) },
          { label: "Overtime", value: overtime ? formatHours(overtime) : "None" },
          { label: "Late", value: late ? formatHours(late) : "None" },
        ]}
      />

      {attendanceQuery.isError && (
        <ErrorState
          message="Could not load your attendance history. Check your connection to the server and try again."
          onRetry={() => void attendanceQuery.refetch()}
        />
      )}

      {attendanceQuery.isLoading ? (
        <SkeletonList rows={6} height="h-12" />
      ) : records.length === 0 ? (
        <Card>
          <EmptyState
            icon={<CalendarDays size={20} />}
            title={`Nothing recorded in ${formatMonthYear(month)}`}
            body="Days you check in on will appear here, with your hours and any overtime."
          />
        </Card>
      ) : (
        <Card padded={false} className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  {["Date", "Progress", "Check In", "Check Out", "Worked", "Status"].map((h, i) => (
                    <th
                      key={h}
                      className={cn(
                        "whitespace-nowrap border-b border-[hsl(var(--border))] px-4 py-3 text-left text-xs font-semibold text-[hsl(var(--foreground-muted))]",
                        i === 4 && "text-right",
                      )}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody data-testid="attendance-history-list">
                {records.map((r) => {
                  const workedPct = Math.min(100, ((r.total_minutes ?? 0) / expectedMinutes) * 100);
                  const otPct = Math.min(40, ((r.overtime_minutes ?? 0) / expectedMinutes) * 100);
                  return (
                    <tr
                      key={r.id}
                      data-testid="attendance-row"
                      className="border-b border-[hsl(var(--border))] last:border-b-0 hover:bg-[hsl(var(--row))]"
                    >
                      <td className="whitespace-nowrap px-4 py-3 font-medium text-[hsl(var(--foreground))]">
                        {formatDate(r.date)}
                      </td>
                      <td className="px-4 py-3">
                        <ProgressBar
                          segments={[
                            { key: "w", percent: workedPct, token: "--primary" },
                            { key: "o", percent: otPct, token: "--warning" },
                          ]}
                        />
                      </td>
                      <td className="num whitespace-nowrap px-4 py-3 text-[hsl(var(--foreground))]">
                        {formatShortTime(r.check_in)}
                      </td>
                      <td
                        className={cn(
                          "num whitespace-nowrap px-4 py-3",
                          r.check_in && !r.check_out
                            ? "font-semibold text-[hsl(var(--destructive))]"
                            : "text-[hsl(var(--foreground))]",
                        )}
                      >
                        {r.check_in && !r.check_out ? "Missing" : formatShortTime(r.check_out)}
                      </td>
                      <td className="num whitespace-nowrap px-4 py-3 text-right font-semibold text-[hsl(var(--foreground))]">
                        {formatHours(r.total_minutes)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge variant={STATUS_VARIANT[r.status]}>{STATUS_LABEL[r.status]}</Badge>
                          {!!r.overtime_minutes && (
                            <Badge variant="warning">+{formatHours(r.overtime_minutes)}</Badge>
                          )}
                          {r.is_regularized && <Badge variant="outline">Corrected</Badge>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Honest dead-end rather than a button that does nothing: there is
          no self-service regularization endpoint on this backend, so the
          app says who to ask instead of pretending it can fix it. */}
      <p className="text-xs leading-relaxed text-[hsl(var(--foreground-muted))]">
        Something wrong with a day? Corrections are made by your HR admin — send them the date and what it should
        say.
      </p>
    </div>
  );
}

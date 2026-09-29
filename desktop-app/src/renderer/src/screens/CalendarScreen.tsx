import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";
import { getHolidaysForYear } from "../services/holidaysService";
import { getMyLeaveRequests } from "../services/leaveService";
import { getMyAttendance } from "../services/attendanceService";
import type { Holiday, LeaveRequestItem } from "../types/hrms";
import { formatDate, formatMonthYear, toIsoDate } from "../lib/format";
import { Badge, Card, cn } from "../components/ui";

/**
 * A real month calendar, in place of what used to only exist as a static
 * design-kit mockup. One grid, three overlays:
 *   - public holidays (from GET /holidays — see the backend note below)
 *   - the employee's own leave, both approved and pending, shown
 *     differently so "this is booked" and "this is still a request"
 *     don't look the same
 *   - a small dot on any day already worked this month, from attendance
 *
 * BACKEND NOTE: GET /holidays had no router behind it at all until this
 * change shipped alongside this screen (see backend/app/api/v1/hrms/
 * holidays.py) — every holiday call was silently 404ing before. If
 * holidays still don't appear after deploying that file, check it was
 * actually registered in app/main.py's _register_routers().
 */

const WEEKDAY_LABELS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

export default function CalendarScreen(): JSX.Element {
  const [cursor, setCursor] = useState(() => startOfMonth(new Date()));
  const year = cursor.getFullYear();

  const holidaysQuery = useQuery({
    queryKey: ["holidays", "year", year],
    queryFn: () => getHolidaysForYear(year),
    staleTime: 60 * 60 * 1000,
  });
  const requestsQuery = useQuery({ queryKey: ["leave", "requests"], queryFn: () => getMyLeaveRequests() });
  const attendanceQuery = useQuery({
    queryKey: ["attendance", "month", `${year}-${cursor.getMonth()}`],
    queryFn: () =>
      getMyAttendance({ from: cursor, to: new Date(year, cursor.getMonth() + 1, 0) }),
  });

  const holidaysByDate = useMemo(() => {
    const map = new Map<string, Holiday>();
    for (const h of holidaysQuery.data ?? []) map.set(h.date, h);
    return map;
  }, [holidaysQuery.data]);

  const leaveByDate = useMemo(() => {
    const map = new Map<string, LeaveRequestItem>();
    for (const r of requestsQuery.data ?? []) {
      if (r.status === "rejected") continue;
      const cursorDate = new Date(`${r.start_date}T00:00:00`);
      const end = new Date(`${r.end_date}T00:00:00`);
      while (cursorDate <= end) {
        map.set(toIsoDate(cursorDate), r);
        cursorDate.setDate(cursorDate.getDate() + 1);
      }
    }
    return map;
  }, [requestsQuery.data]);

  const workedDates = useMemo(() => {
    const set = new Set<string>();
    for (const r of attendanceQuery.data ?? []) {
      if (r.check_in) set.add(r.date);
    }
    return set;
  }, [attendanceQuery.data]);

  const days = useMemo(() => buildGrid(cursor), [cursor]);
  const todayIso = toIsoDate(new Date());

  // Upcoming events within the currently displayed month, soonest first —
  // the list under the grid the mockup showed.
  const upcoming = useMemo(() => {
    const items: Array<{ date: string; label: string; kind: "holiday" | "leave" }> = [];
    for (const h of holidaysQuery.data ?? []) {
      if (h.date.startsWith(`${year}-${String(cursor.getMonth() + 1).padStart(2, "0")}`)) {
        items.push({ date: h.date, label: h.name, kind: "holiday" });
      }
    }
    for (const r of requestsQuery.data ?? []) {
      if (r.status === "rejected") continue;
      if (r.start_date.startsWith(`${year}-${String(cursor.getMonth() + 1).padStart(2, "0")}`)) {
        items.push({ date: r.start_date, label: `${r.leave_type} · ${r.status}`, kind: "leave" });
      }
    }
    return items.sort((a, b) => a.date.localeCompare(b.date)).slice(0, 6);
  }, [holidaysQuery.data, requestsQuery.data, cursor, year]);

  return (
    <div className="flex w-full flex-col gap-[18px] p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-[22px] font-semibold tracking-tight text-[hsl(var(--foreground))]">
            Calendar
          </h1>
          <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
            Public holidays and your own leave, laid out by month
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setCursor((c) => addMonths(c, -1))}
            aria-label="Previous month"
            className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-control)] border border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--secondary))] hover:text-[hsl(var(--primary))]"
          >
            <ChevronLeft size={15} />
          </button>
          <span className="min-w-[150px] text-center text-sm font-semibold text-[hsl(var(--foreground))]">
            {formatMonthYear(cursor)}
          </span>
          <button
            onClick={() => setCursor((c) => addMonths(c, 1))}
            aria-label="Next month"
            className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-control)] border border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--secondary))] hover:text-[hsl(var(--primary))]"
          >
            <ChevronRight size={15} />
          </button>
          <button
            onClick={() => setCursor(startOfMonth(new Date()))}
            className="ml-1 rounded-[var(--radius-control)] border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs font-semibold text-[hsl(var(--primary))] hover:bg-[hsl(var(--secondary))]"
          >
            Today
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[1fr_280px]">
        <Card>
          <div className="grid grid-cols-7 gap-[5px]">
            {WEEKDAY_LABELS.map((d) => (
              <div key={d} className="py-1 text-center text-[11px] font-semibold text-[hsl(var(--foreground-muted))]">
                {d}
              </div>
            ))}

            {days.map(({ date, inMonth }) => {
              const iso = toIsoDate(date);
              const holiday = holidaysByDate.get(iso);
              const leave = leaveByDate.get(iso);
              const isToday = iso === todayIso;
              const worked = workedDates.has(iso);

              return (
                <div
                  key={iso}
                  className={cn(
                    "relative min-h-[58px] rounded-[10px] border p-1.5 text-xs",
                    !inMonth && "opacity-40",
                    leave
                      ? leave.status === "approved"
                        ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))] text-white"
                        : "border-[hsl(var(--warning))] bg-[hsl(var(--status-warning-bg))] text-[hsl(var(--status-warning-fg))]"
                      : holiday
                        ? "border-[hsl(var(--secondary))] bg-[hsl(var(--secondary))] text-[hsl(var(--primary))]"
                        : "border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--foreground))]",
                    isToday && "outline outline-2 -outline-offset-2 outline-[hsl(var(--primary))]",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className={cn("font-medium", isToday && "font-bold")}>{date.getDate()}</span>
                    {worked && !leave && !holiday && (
                      <span className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--success))]" aria-hidden />
                    )}
                  </div>
                  {(holiday || leave) && (
                    <p className="mt-0.5 truncate text-[10px] font-medium leading-tight">
                      {leave ? (leave.status === "approved" ? "Leave" : "Pending") : holiday?.name}
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-[hsl(var(--border))] pt-3 text-[11px] text-[hsl(var(--foreground-muted))]">
            <LegendItem swatch="bg-[hsl(var(--primary))]" label="Your approved leave" />
            <LegendItem swatch="bg-[hsl(var(--status-warning-bg))] border border-[hsl(var(--warning))]" label="Pending leave" />
            <LegendItem swatch="bg-[hsl(var(--secondary))]" label="Public holiday" />
            <LegendItem swatch="bg-[hsl(var(--success))] !h-2 !w-2 !rounded-full" label="Worked" dot />
          </div>
        </Card>

        <Card>
          <h3 className="mb-3 font-heading text-sm font-semibold text-[hsl(var(--foreground))]">
            This month
          </h3>
          {holidaysQuery.isLoading || requestsQuery.isLoading ? (
            <p className="text-xs text-[hsl(var(--foreground-muted))]">Loading…</p>
          ) : upcoming.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-6 text-center">
              <CalendarDays size={18} className="text-[hsl(var(--foreground-muted))]" />
              <p className="text-xs text-[hsl(var(--foreground-muted))]">
                No holidays or leave in {formatMonthYear(cursor)}.
              </p>
            </div>
          ) : (
            <ul className="flex flex-col gap-2">
              {upcoming.map((item, i) => (
                <li key={`${item.date}-${i}`} className="flex items-center justify-between gap-2">
                  <span className="min-w-0 flex-1 truncate text-xs text-[hsl(var(--foreground))]">
                    {item.label}
                  </span>
                  <Badge variant={item.kind === "holiday" ? "info" : "default"}>{formatDate(item.date)}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function LegendItem({ swatch, label, dot = false }: { swatch: string; label: string; dot?: boolean }): JSX.Element {
  return (
    <span className="flex items-center gap-1.5">
      <span aria-hidden className={cn(dot ? "inline-block" : "h-2.5 w-2.5 rounded-[3px]", swatch)} />
      {label}
    </span>
  );
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function addMonths(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth() + n, 1);
}

/** Monday-start 6-week grid, padded with the adjacent months' trailing
 * and leading days so every row is full. */
function buildGrid(monthStart: Date): Array<{ date: Date; inMonth: boolean }> {
  const firstWeekday = (monthStart.getDay() + 6) % 7; // 0 = Monday
  const gridStart = new Date(monthStart);
  gridStart.setDate(gridStart.getDate() - firstWeekday);

  const days: Array<{ date: Date; inMonth: boolean }> = [];
  const cursor = new Date(gridStart);
  for (let i = 0; i < 42; i++) {
    days.push({ date: new Date(cursor), inMonth: cursor.getMonth() === monthStart.getMonth() });
    cursor.setDate(cursor.getDate() + 1);
  }
  return days;
}

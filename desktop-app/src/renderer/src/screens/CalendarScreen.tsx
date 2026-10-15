import { useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { CalendarDays, ChevronLeft, ChevronRight, Flag, Plus, Umbrella } from "lucide-react";
import { getHolidaysForYear } from "../services/holidaysService";
import { getMyLeaveRequests } from "../services/leaveService";
import { getMyAttendance } from "../services/attendanceService";
import type { Holiday, LeaveRequestItem } from "../types/hrms";
import { toIsoDate } from "../lib/format";
import { Badge, Button, Card, EmptyState, Skeleton, cn } from "../components/ui";

/**
 * Calendar — the employee's own month at a glance.
 *
 * Left: a "Coming up" list (public holidays + the employee's own leave,
 * soonest first) under a Request leave button. Right: Day / Week / Month
 * views of the same events. In the month and week views an event that runs
 * over several days is ONE bar across those days (not a coloured cell per
 * day), the days that belong to the neighbouring months are hatched, and
 * today is the filled number.
 *
 * Events:
 *   - public holidays — GET /holidays?year=… (open to every employee)
 *   - the employee's own leave, approved and pending (rejected is hidden),
 *     in the leave type's own colour; pending is dashed and says so
 *   - a small dot on every day already worked this month (attendance)
 */

type View = "day" | "week" | "month";

interface CalEvent {
  id: string;
  kind: "holiday" | "leave";
  title: string;
  /** ISO dates, inclusive. */
  start: string;
  end: string;
  color: string;
  pending?: boolean;
  /** Second line in the list: "Public holiday", "3 days · Approved"… */
  detail: string;
}

const HOLIDAY_COLOR = "#2E90FA"; // --blue-500
const FALLBACK_LEAVE_COLOR = "#7F56D9"; // --brand-600
const WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
const MAX_LANES_MONTH = 3;

// ── Date helpers (local time, Monday-first weeks) ───────────────────────────

const parseIso = (iso: string): Date => new Date(`${iso}T00:00:00`);
const addDays = (d: Date, n: number): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const addMonths = (d: Date, n: number): Date => new Date(d.getFullYear(), d.getMonth() + n, 1);
const startOfWeek = (d: Date): Date => addDays(d, -((d.getDay() + 6) % 7));

function monthGrid(cursor: Date): Date[] {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const start = startOfWeek(first);
  const lastDay = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
  // Five rows when the month fits, six when it needs them.
  const weeks = Math.ceil((((first.getDay() + 6) % 7) + lastDay.getDate()) / 7);
  return Array.from({ length: weeks * 7 }, (_, i) => addDays(start, i));
}

const fmt = (d: Date, o: Intl.DateTimeFormatOptions): string => d.toLocaleDateString("en-US", o);

function rangeLabel(start: string, end: string): string {
  const s = parseIso(start);
  const e = parseIso(end);
  if (start === end) return fmt(s, { day: "numeric", month: "long", year: "numeric" });
  if (s.getMonth() === e.getMonth() && s.getFullYear() === e.getFullYear()) {
    return `${s.getDate()}–${e.getDate()} ${fmt(e, { month: "long", year: "numeric" })}`;
  }
  return `${fmt(s, { day: "numeric", month: "short" })} – ${fmt(e, { day: "numeric", month: "short", year: "numeric" })}`;
}

const validHex = (c: string | null | undefined): c is string => !!c && /^#[0-9a-f]{6}$/i.test(c);

// ── Screen ──────────────────────────────────────────────────────────────────

export default function CalendarScreen({ onNavigate }: { onNavigate?: (tab: "leave") => void }): JSX.Element {
  const [view, setView] = useState<View>("month");
  const [cursor, setCursor] = useState(() => new Date());
  const [showAll, setShowAll] = useState(false);

  const today = useMemo(() => new Date(), []);
  const todayIso = toIsoDate(today);

  // Days that will be drawn, so we know which years' holidays are needed
  // (a December grid shows January days).
  const gridDays = useMemo(() => monthGrid(cursor), [cursor]);
  const years = useMemo(() => {
    const set = new Set<number>([
      today.getFullYear(),
      today.getFullYear() + 1,
      gridDays[0]?.getFullYear() ?? today.getFullYear(),
      gridDays[gridDays.length - 1]?.getFullYear() ?? today.getFullYear(),
      cursor.getFullYear(),
    ]);
    return [...set].sort();
  }, [today, gridDays, cursor]);

  const holidayQueries = useQueries({
    queries: years.map((y) => ({
      queryKey: ["holidays", "year", y],
      queryFn: () => getHolidaysForYear(y),
      staleTime: 60 * 60 * 1000,
      retry: false,
    })),
  });
  const requestsQuery = useQuery({
    queryKey: ["leave", "requests"],
    queryFn: () => getMyLeaveRequests(),
    retry: false,
  });
  const monthKey = `${cursor.getFullYear()}-${cursor.getMonth()}`;
  const attendanceQuery = useQuery({
    queryKey: ["attendance", "month", monthKey],
    queryFn: () => getMyAttendance({ from: new Date(cursor.getFullYear(), cursor.getMonth(), 1), to: new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0) }),
    retry: false,
  });

  const loading = holidayQueries.some((q) => q.isLoading) || requestsQuery.isLoading;
  const holidayData = holidayQueries.map((q) => q.data).filter(Boolean) as Holiday[][];

  const events = useMemo<CalEvent[]>(() => {
    const out: CalEvent[] = [];
    const seen = new Set<string>();
    for (const h of holidayData.flat()) {
      if (seen.has(h.id)) continue;
      seen.add(h.id);
      out.push({
        id: `h-${h.id}`,
        kind: "holiday",
        title: h.name,
        start: h.date,
        end: h.date,
        color: HOLIDAY_COLOR,
        detail: h.is_optional ? "Optional holiday" : "Public holiday",
      });
    }
    for (const r of requestsQuery.data ?? ([] as LeaveRequestItem[])) {
      if (r.status === "rejected") continue;
      const days = `${r.total_days} day${r.total_days === 1 ? "" : "s"}`;
      out.push({
        id: `l-${r.id}`,
        kind: "leave",
        title: r.leave_type,
        start: r.start_date,
        end: r.end_date,
        color: validHex(r.leave_type_color) ? r.leave_type_color : FALLBACK_LEAVE_COLOR,
        pending: r.status === "pending",
        detail: `${days} · ${r.status === "pending" ? "Pending approval" : "Approved"}`,
      });
    }
    return out;
    // holidayData is rebuilt each render; key on the query data instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [holidayQueries.map((q) => q.dataUpdatedAt).join(","), requestsQuery.data]);

  const workedDates = useMemo(() => {
    const set = new Set<string>();
    for (const r of attendanceQuery.data ?? []) if (r.check_in) set.add(r.date);
    return set;
  }, [attendanceQuery.data]);

  const upcoming = useMemo(
    () => events.filter((e) => e.end >= todayIso).sort((a, b) => a.start.localeCompare(b.start)).slice(0, 20),
    [events, todayIso],
  );
  const shown = showAll ? upcoming : upcoming.slice(0, 4);

  // ── Header: title and stepping depend on the view ─────────────────────────
  const title =
    view === "month"
      ? fmt(cursor, { month: "long", year: "numeric" })
      : view === "week"
        ? weekTitle(cursor)
        : fmt(cursor, { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  function step(dir: 1 | -1): void {
    setCursor((c) => (view === "month" ? addMonths(c, dir) : view === "week" ? addDays(c, 7 * dir) : addDays(c, dir)));
  }

  function openDay(d: Date): void {
    setCursor(d);
    setView("day");
  }

  return (
    <div className="flex w-full flex-col gap-4 p-6">
      <header>
        <h1 className="font-heading text-xl font-semibold text-[hsl(var(--foreground))]">Calendar</h1>
        <p className="mt-0.5 text-sm text-[hsl(var(--foreground-muted))]">
          Public holidays and your own leave, by day, week or month
        </p>
      </header>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        {/* ── Coming up ─────────────────────────────────────────────────── */}
        <Card padded={false} className="flex flex-col self-start">
          <div className="p-5 pb-4">
            <Button className="w-full" onClick={() => onNavigate?.("leave")} data-testid="calendar-request-leave">
              <Plus size={16} aria-hidden />
              Request leave
            </Button>
            <h2 className="mt-5 font-heading text-base font-semibold text-[hsl(var(--foreground))]">Coming up</h2>
          </div>

          <div className="border-t border-[hsl(var(--border))]">
            {loading ? (
              <div className="flex flex-col gap-3 p-5">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-14 w-full rounded-lg" />
                ))}
              </div>
            ) : upcoming.length === 0 ? (
              <EmptyState
                icon={<CalendarDays size={20} />}
                title="Nothing coming up"
                body="Holidays and your approved or pending leave will show here."
              />
            ) : (
              <ul data-testid="calendar-upcoming" className="divide-y divide-[hsl(var(--border))]">
                {shown.map((e) => (
                  <li key={e.id} className="flex gap-3 px-5 py-4">
                    <span
                      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
                      style={{ backgroundColor: `${e.color}1F`, color: e.color }}
                      aria-hidden
                    >
                      {e.kind === "leave" ? <Umbrella size={18} /> : <Flag size={18} />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-[hsl(var(--foreground))]">{e.title}</p>
                      <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
                        {e.start <= todayIso && e.end >= todayIso ? "Today · " : ""}
                        {rangeLabel(e.start, e.end)}
                      </p>
                      <p className="mt-0.5 flex items-center gap-1.5 text-xs text-[hsl(var(--foreground-muted))]">
                        {e.detail}
                        {e.pending && <Badge variant="warning">Pending</Badge>}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {upcoming.length > 4 && (
            <div className="border-t border-[hsl(var(--border))] p-4 text-center">
              <Button variant="secondary" size="sm" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Show less" : "See more"}
              </Button>
            </div>
          )}
        </Card>

        {/* ── Calendar ──────────────────────────────────────────────────── */}
        <Card padded={false} className="min-w-0">
          <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 p-5">
            <div>
              <button
                type="button"
                onClick={() => setCursor(new Date())}
                className="rounded-md px-1 py-1 text-sm font-medium text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--primary))]"
              >
                Today
              </button>
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => step(-1)}
                aria-label={`Previous ${view}`}
                className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--secondary))] hover:text-[hsl(var(--foreground))]"
              >
                <ChevronLeft size={20} />
              </button>
              <h2
                data-testid="calendar-title"
                className="min-w-[10ch] text-center font-heading text-xl font-semibold text-[hsl(var(--foreground))]"
              >
                {title}
              </h2>
              <button
                type="button"
                onClick={() => step(1)}
                aria-label={`Next ${view}`}
                className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--secondary))] hover:text-[hsl(var(--foreground))]"
              >
                <ChevronRight size={20} />
              </button>
            </div>

            <div className="flex justify-end">
              <div
                role="group"
                aria-label="Calendar view"
                className="inline-flex overflow-hidden rounded-lg border border-[hsl(var(--border-strong))] shadow-[var(--shadow-xs)]"
              >
                {(["day", "week", "month"] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    aria-pressed={view === v}
                    onClick={() => setView(v)}
                    className={cn(
                      "px-3.5 py-2 text-sm font-medium capitalize transition-colors",
                      view === v
                        ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                        : "bg-[hsl(var(--card))] text-[hsl(var(--foreground-subtle))] hover:bg-[hsl(var(--secondary))]",
                    )}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="px-5 pb-5">
            {view === "month" && (
              <MonthView
                days={gridDays}
                cursor={cursor}
                events={events}
                workedDates={workedDates}
                todayIso={todayIso}
                onOpenDay={openDay}
              />
            )}
            {view === "week" && (
              <WeekView
                cursor={cursor}
                events={events}
                workedDates={workedDates}
                todayIso={todayIso}
                onOpenDay={openDay}
              />
            )}
            {view === "day" && <DayView date={cursor} events={events} worked={workedDates.has(toIsoDate(cursor))} />}
          </div>

          <Legend />
        </Card>
      </div>
    </div>
  );
}

function weekTitle(cursor: Date): string {
  const s = startOfWeek(cursor);
  const e = addDays(s, 6);
  return s.getMonth() === e.getMonth()
    ? `${s.getDate()}–${e.getDate()} ${fmt(e, { month: "long", year: "numeric" })}`
    : `${fmt(s, { day: "numeric", month: "short" })} – ${fmt(e, { day: "numeric", month: "short", year: "numeric" })}`;
}

// ── Month + week grids ──────────────────────────────────────────────────────

interface GridProps {
  events: CalEvent[];
  workedDates: Set<string>;
  todayIso: string;
  onOpenDay: (d: Date) => void;
}

function MonthView({ days, cursor, ...rest }: GridProps & { days: Date[]; cursor: Date }): JSX.Element {
  const weeks = Array.from({ length: days.length / 7 }, (_, i) => days.slice(i * 7, i * 7 + 7));
  return (
    <div data-testid="calendar-month" className="overflow-hidden rounded-xl border border-[hsl(var(--border))]">
      <WeekdayHeader />
      {weeks.map((week) => (
        <WeekRow
          key={toIsoDate(week[0] as Date)}
          week={week}
          month={cursor.getMonth()}
          maxLanes={MAX_LANES_MONTH}
          cellHeight="min-h-[104px]"
          {...rest}
        />
      ))}
    </div>
  );
}

function WeekView({ cursor, ...rest }: GridProps & { cursor: Date }): JSX.Element {
  const start = startOfWeek(cursor);
  const week = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  return (
    <div data-testid="calendar-week" className="overflow-hidden rounded-xl border border-[hsl(var(--border))]">
      <WeekdayHeader />
      <WeekRow week={week} month={null} maxLanes={8} cellHeight="min-h-[320px]" {...rest} />
    </div>
  );
}

function WeekdayHeader(): JSX.Element {
  return (
    <div className="grid grid-cols-7 bg-[hsl(var(--background-subtle))]">
      {WEEKDAYS.map((d) => (
        <div
          key={d}
          className="py-3 text-center text-xs font-semibold tracking-wide text-[hsl(var(--foreground-subtle))]"
        >
          {d}
        </div>
      ))}
    </div>
  );
}

interface Segment {
  event: CalEvent;
  col: number; // 0-based start column
  span: number;
  lane: number;
  contLeft: boolean;
  contRight: boolean;
}

/** Cuts every event that touches this week into one segment, then packs the
 * segments into lanes so overlapping events stack instead of covering each
 * other. Longer events are placed first so they get the top lane. */
function layoutWeek(weekIso: string[], events: CalEvent[]): Segment[] {
  const first = weekIso[0] as string;
  const last = weekIso[6] as string;
  const raw = events
    .filter((e) => e.start <= last && e.end >= first)
    .map((e) => {
      const s = e.start < first ? first : e.start;
      const t = e.end > last ? last : e.end;
      const col = weekIso.indexOf(s);
      const endCol = weekIso.indexOf(t);
      return { event: e, col, span: endCol - col + 1, contLeft: e.start < first, contRight: e.end > last };
    })
    .sort((a, b) => a.col - b.col || b.span - a.span || a.event.kind.localeCompare(b.event.kind));

  const laneEnds: number[] = [];
  return raw.map((seg) => {
    let lane = laneEnds.findIndex((end) => end < seg.col);
    if (lane === -1) lane = laneEnds.length;
    laneEnds[lane] = seg.col + seg.span - 1;
    return { ...seg, lane };
  });
}

const HATCH =
  "repeating-linear-gradient(135deg, transparent 0 7px, hsl(var(--blue-100) / 0.9) 7px 8px)";

function WeekRow({
  week, month, maxLanes, cellHeight, events, workedDates, todayIso, onOpenDay,
}: GridProps & { week: Date[]; month: number | null; maxLanes: number; cellHeight: string }): JSX.Element {
  const weekIso = week.map(toIsoDate);
  const segments = useMemo(() => layoutWeek(weekIso, events), [weekIso.join(","), events]); // eslint-disable-line react-hooks/exhaustive-deps
  const visible = segments.filter((s) => s.lane < maxLanes);

  // Per-day count of events that did not fit, for the "+n more" link.
  const hidden = weekIso.map((_, i) =>
    segments.filter((s) => s.lane >= maxLanes && i >= s.col && i < s.col + s.span).length,
  );

  return (
    <div className="relative border-t border-[hsl(var(--border))]">
      <div className="grid grid-cols-7">
        {week.map((d, i) => {
          const iso = weekIso[i] as string;
          const outside = month !== null && d.getMonth() !== month;
          const isToday = iso === todayIso;
          return (
            <div
              key={iso}
              className={cn(
                "relative flex flex-col border-l border-[hsl(var(--border))] first:border-l-0",
                cellHeight,
              )}
              style={outside ? { backgroundImage: HATCH } : undefined}
            >
              <div className="flex items-start justify-end gap-1.5 px-2 pt-2">
                {workedDates.has(iso) && !outside && (
                  <span
                    title="You worked this day"
                    className="mt-2 h-1.5 w-1.5 rounded-full bg-[hsl(var(--success))]"
                    aria-label="Worked"
                  />
                )}
                <button
                  type="button"
                  onClick={() => onOpenDay(d)}
                  aria-label={fmt(d, { weekday: "long", day: "numeric", month: "long" })}
                  className={cn(
                    "num flex h-7 min-w-7 items-center justify-center rounded-full px-1.5 text-sm font-medium transition-colors",
                    isToday
                      ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                      : outside
                        ? "text-[hsl(var(--gray-400))] hover:bg-[hsl(var(--secondary))]"
                        : "text-[hsl(var(--foreground))] hover:bg-[hsl(var(--secondary))]",
                  )}
                >
                  {d.getDate()}
                </button>
              </div>
              {hidden[i]! > 0 && (
                <button
                  type="button"
                  onClick={() => onOpenDay(d)}
                  className="mt-auto px-2 pb-1.5 text-left text-xs font-medium text-[hsl(var(--primary))] hover:underline"
                >
                  +{hidden[i]} more
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* Event bars: one per event per week, spanning its days. The layer
          ignores the pointer so the day numbers underneath stay clickable;
          each bar opts back in for its tooltip. */}
      <div
        className="pointer-events-none absolute inset-x-0 top-[44px] grid grid-cols-7 gap-y-1"
        style={{ gridAutoRows: "24px" }}
      >
        {visible.map((s) => (
          <EventBar key={`${s.event.id}-${s.col}`} seg={s} />
        ))}
      </div>
    </div>
  );
}

function EventBar({ seg }: { seg: Segment }): JSX.Element {
  const { event: e } = seg;
  return (
    <div
      title={`${e.title} · ${rangeLabel(e.start, e.end)}${e.pending ? " (pending)" : ""}`}
      className={cn(
        "pointer-events-auto flex items-center truncate px-2 text-xs font-medium",
        !seg.contLeft && "ml-1 rounded-l-md border-l-[3px]",
        !seg.contRight && "mr-1 rounded-r-md",
        e.pending && "border-dashed",
      )}
      style={{
        gridColumn: `${seg.col + 1} / span ${seg.span}`,
        gridRow: seg.lane + 1,
        backgroundColor: `${e.color}${e.pending ? "14" : "24"}`,
        borderLeftColor: e.color,
        color: `color-mix(in srgb, ${e.color} 78%, #000)`,
      }}
    >
      <span className="truncate">
        {e.title}
        {e.pending ? " (pending)" : ""}
      </span>
    </div>
  );
}

// ── Day view ────────────────────────────────────────────────────────────────

function DayView({ date, events, worked }: { date: Date; events: CalEvent[]; worked: boolean }): JSX.Element {
  const iso = toIsoDate(date);
  const todays = events.filter((e) => e.start <= iso && e.end >= iso);

  return (
    <div data-testid="calendar-day" className="rounded-xl border border-[hsl(var(--border))]">
      {todays.length === 0 ? (
        <EmptyState
          icon={<CalendarDays size={20} />}
          title="Nothing on this day"
          body={worked ? "You worked this day. No holidays or leave fall on it." : "No holidays or leave fall on this day."}
        />
      ) : (
        <ul className="divide-y divide-[hsl(var(--border))]">
          {todays.map((e) => (
            <li key={e.id} className="flex items-center gap-4 px-5 py-4">
              <span className="h-10 w-1 shrink-0 rounded-full" style={{ backgroundColor: e.color }} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-[hsl(var(--foreground))]">{e.title}</p>
                <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
                  {rangeLabel(e.start, e.end)} · {e.detail}
                </p>
              </div>
              <Badge variant={e.kind === "holiday" ? "info" : e.pending ? "warning" : "success"}>
                {e.kind === "holiday" ? "Holiday" : e.pending ? "Pending" : "Approved"}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Legend(): JSX.Element {
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-1.5 border-t border-[hsl(var(--border))] px-5 py-3 text-xs text-[hsl(var(--foreground-muted))]">
      <LegendItem swatch={<span className="h-2.5 w-4 rounded-sm" style={{ backgroundColor: `${FALLBACK_LEAVE_COLOR}33`, borderLeft: `3px solid ${FALLBACK_LEAVE_COLOR}` }} />} label="Approved leave" />
      <LegendItem swatch={<span className="h-2.5 w-4 rounded-sm border border-dashed border-[hsl(var(--warning))]" />} label="Pending leave" />
      <LegendItem swatch={<span className="h-2.5 w-4 rounded-sm" style={{ backgroundColor: `${HOLIDAY_COLOR}33`, borderLeft: `3px solid ${HOLIDAY_COLOR}` }} />} label="Holiday" />
      <LegendItem swatch={<span className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--success))]" />} label="Worked" />
    </div>
  );
}

function LegendItem({ swatch, label }: { swatch: JSX.Element; label: string }): JSX.Element {
  return (
    <span className="flex items-center gap-1.5">
      {swatch}
      {label}
    </span>
  );
}

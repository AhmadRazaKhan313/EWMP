import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Clock, CalendarCheck, CalendarClock, CalendarRange, Bell, ChevronRight,
  Umbrella, Coffee, Plus, PartyPopper,
} from "lucide-react";
import { useAuthStore } from "../store/authStore";
import { getMyLeaveRequests } from "../services/leaveService";
import { getUpcomingHolidays } from "../services/holidaysService";
import { getUnreadNotificationCount } from "../services/notificationsService";
import { getMyAttendance } from "../services/attendanceService";
import {
  effectiveSessionMinutes, getMyRecentSessions, sessionsToday, sumMinutesThisWeek, sumMinutesToday,
} from "../services/workSessionsService";
import type { WorkSessionItem } from "../types/hrms";
import { getMyLeaveBalances } from "../services/leaveService";
import { listShifts, pickDefaultShift, dailyHoursForShift } from "../services/shiftsService";
import { useMonthSummary } from "../hooks/useMonthSummary";
import { useTimerStore } from "../store/timerStore";
import {
  formatClockTime, formatDate, formatHours, formatLongDate, formatMonthYear, toIsoDate,
} from "../lib/format";
import {
  Badge, Button, Card, CardHeader, EmptyState, ProgressBar, Skeleton, SkeletonList, StatBand, StatusDot, cn,
} from "../components/ui";
import CheckInWidget from "./CheckInWidget";

/**
 * Employee dashboard — the desktop counterpart of the admin web app's
 * Timesheet screen, rebuilt to match it: indigo stat band across the top,
 * then Daily Reports / Clock In / My Requests in three columns, then
 * Public Holidays along the bottom.
 *
 * WHAT CHANGED vs the old version, and why:
 *
 *  - The old screen showed exactly two numbers (today's hours, this
 *    week's hours) and a greeting card. The band now shows the four
 *    figures the admin UI shows — vacation total, used, required hours,
 *    actual hours — assembled by useMonthSummary from four self-scoped
 *    endpoints. See that hook for how "required" is derived and why.
 *
 *  - "Active Employees" from the admin layout is replaced by MY REQUESTS.
 *    An employee does not need a roster of colleagues; they need to know
 *    whether their own leave request has been approved yet. Same slot,
 *    same shape, useful content.
 *
 *  - Daily Reports now lists EVERY check-in/check-out pair from today as
 *    its own timeline row, sourced from GET /work-sessions/me rather
 *    than the single attendance aggregate. The aggregate's check_in is
 *    just whichever session started first and its check_out is whichever
 *    ended last, so it was structurally incapable of showing a second
 *    check-in later the same day — the card just kept displaying the
 *    first pair no matter how many more times someone clocked in. See
 *    SessionRow below and workSessionsService.sessionsToday().
 *
 * It still deliberately does NOT call GET /dashboard/stats — that returns
 * org-wide admin counts (total employees, open tickets, devices online),
 * nothing scoped to "me".
 */
export default function DashboardScreen({
  onNavigate,
}: {
  onNavigate?: (
    tab: "leave" | "attendance" | "calendar" | "notifications" | "payslips" | "profile" | "dashboard",
  ) => void;
}): JSX.Element {
  const user = useAuthStore((s) => s.user);
  const timerStatus = useTimerStore((s) => s.status);
  const today = useMemo(() => new Date(), []);
  const summary = useMonthSummary(today);

  const shiftsQuery = useQuery({ queryKey: ["shifts"], queryFn: listShifts, staleTime: 60 * 60 * 1000 });
  const shift = pickDefaultShift(shiftsQuery.data);
  const expectedHours = dailyHoursForShift(shift);

  // The day's individual check-in/check-out PAIRS — not the attendance
  // aggregate. Same queryKey as TodayWeekStrip's sessions query below, so
  // TanStack Query dedupes this into one network call either way.
  //
  // BUG THIS REPLACES: Daily Reports used to read a single `attendance`
  // record and show its check_in/check_out fields directly. That record
  // is a daily AGGREGATE — one row per day, its check_in is whichever
  // session started first and its check_out is whichever ended last (or
  // null while the day is still open). Checking out and checking back in
  // later the same day is a perfectly normal thing to do (a lunch
  // errand, a forgotten badge), and every session after the first was
  // invisible: the card only ever showed "the 1st one". A second
  // check-in also didn't visibly update anything, because the aggregate
  // record's check_in field doesn't change on a later session — it
  // looked like the check-in had silently failed. Reading the individual
  // work-sessions list instead fixes both.
  const sessionsQuery = useQuery({
    queryKey: ["work-sessions", "me", "recent"],
    queryFn: () => getMyRecentSessions(),
    refetchInterval: 120_000,
  });
  const todaysSessions = sessionsQuery.data ? sessionsToday(sessionsQuery.data) : [];

  // Daily aggregate kept for overtime/late — figures the backend
  // computes once per day, not something meaningful per session.
  const attendanceTodayQuery = useQuery({
    queryKey: ["attendance", "today", toIsoDate(today)],
    queryFn: () => getMyAttendance({ from: today, to: today }),
    refetchInterval: 120_000,
  });
  const attendanceToday = attendanceTodayQuery.data?.[0] ?? null;

  const requestsQuery = useQuery({ queryKey: ["leave", "requests"], queryFn: () => getMyLeaveRequests() });
  const holidaysQuery = useQuery({ queryKey: ["holidays", "upcoming"], queryFn: getUpcomingHolidays });
  const unreadQuery = useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: getUnreadNotificationCount,
    refetchInterval: 60_000,
  });

  const firstName = user?.full_name?.split(" ")[0] ?? "there";
  const hour = today.getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  return (
    <div className="flex w-full flex-col gap-[18px] p-6">
      {/* Header — "Timesheet, 16 September 2026" in the admin UI's exact
          two-weight treatment: label semibold, date in muted regular. */}
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-[22px] font-semibold tracking-tight text-[hsl(var(--foreground))]">
            Timesheet, <span className="font-normal text-[hsl(var(--foreground-muted))]">{formatLongDate(today)}</span>
          </h1>
          <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
            {greeting}, {firstName}
            {shift ? ` · ${shift.name} ${shift.start_time.slice(0, 5)}–${shift.end_time.slice(0, 5)}` : ""}
          </p>
        </div>
        <Button onClick={() => onNavigate?.("leave")}>
          <Plus size={16} />
          New Request
        </Button>
      </header>

      {/* ── Indigo stat band ─────────────────────────────────────────── */}
      {summary.isLoading ? (
        <Skeleton className="h-[126px] w-full rounded-[var(--radius-card)]" />
      ) : (
        <StatBand
          items={[
            {
              icon: <Clock size={19} />,
              label: "Total Vacation Days",
              value: `${round1(summary.vacationEntitledDays + summary.vacationCarriedDays)} Days`,
              breakdown: [
                `${round1(summary.vacationCarriedDays)} carried over`,
                `${round1(summary.vacationEntitledDays)} this year`,
              ],
              testId: "stat-vacation-total",
            },
            {
              icon: <CalendarCheck size={19} />,
              label: "Used Days",
              value: `${round1(summary.vacationUsedDays)} Days`,
              breakdown: [
                `${round1(summary.vacationPendingDays)} pending`,
                `${round1(summary.vacationRemainingDays)} remaining`,
              ],
              testId: "stat-vacation-used",
            },
            {
              icon: <CalendarClock size={19} />,
              label: "Required Working Hours",
              value: formatHours(summary.requiredMinutes),
              breakdown: [`${summary.workingDaysInMonth} working days`, formatMonthYear(today)],
              testId: "stat-required-hours",
            },
            {
              icon: <CalendarRange size={19} />,
              label: "Actual Working Hours",
              value: formatHours(summary.workedMinutes),
              breakdown: [
                summary.overtimeMinutes > 0 ? `+${formatHours(summary.overtimeMinutes)} overtime` : "No overtime",
                balanceLabel(summary.workedMinutes, summary.requiredMinutes),
              ],
              testId: "stat-actual-hours",
            },
          ]}
        />
      )}

      {/* Kept for the existing test contract (stat-today-hours /
          stat-week-hours), and genuinely useful as the "right now"
          counterpart to the band's month figures. */}
      <TodayWeekStrip expectedHours={expectedHours} />

      {/* ── Three columns ────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-3">
        {/* Daily Reports */}
        <Card>
          <CardHeader title="Daily Reports" />
          <div className="mb-4 flex items-center gap-3 rounded-[var(--radius-control)] bg-[hsl(var(--secondary))] px-3.5 py-2.5">
            <span className="text-sm font-semibold text-[hsl(var(--secondary-foreground))]">Selected</span>
            <span className="num text-sm font-semibold text-[hsl(var(--foreground))]">{toIsoDate(today)}</span>
            <CalendarRange size={17} className="ml-auto text-[hsl(var(--primary))]" />
          </div>

          {sessionsQuery.isLoading ? (
            <SkeletonList rows={2} height="h-14" />
          ) : todaysSessions.length > 0 ? (
            <>
              <ol className="flex flex-col">
                {todaysSessions.map((session, i) => (
                  <SessionRow key={session.id} session={session} isLast={i === todaysSessions.length - 1} />
                ))}
              </ol>

              <dl className="mt-4 space-y-2 border-t border-[hsl(var(--border))] pt-3 text-sm">
                <RowStat label="Worked today" value={formatHours(sumMinutesToday(sessionsQuery.data ?? []))} />
                {!!attendanceToday?.overtime_minutes && (
                  <RowStat
                    label="Overtime"
                    value={formatHours(attendanceToday.overtime_minutes)}
                    tone="text-[hsl(var(--warning))]"
                  />
                )}
                {!!attendanceToday?.late_minutes && (
                  <RowStat
                    label="Late by"
                    value={`${attendanceToday.late_minutes}m`}
                    tone="text-[hsl(var(--warning))]"
                  />
                )}
              </dl>

              {timerStatus === "on_break" && (
                <div className="mt-3 flex items-center gap-2 rounded-[var(--radius-control)] bg-[hsl(var(--status-warning-bg))] px-3 py-2.5 text-xs font-medium text-[hsl(var(--status-warning-fg))]">
                  <Coffee size={14} />
                  On break — your working timer is paused
                </div>
              )}
            </>
          ) : (
            <EmptyState
              icon={<Clock size={20} />}
              title="Nothing recorded yet today"
              body="Check in from the card beside this one and your times will appear here."
            />
          )}
        </Card>

        {/* Clock In */}
        <Card>
          <CardHeader
            title="Clock In"
            action={
              <Badge variant={timerStatus === "active" ? "warning" : "outline"}>
                {shift ? shift.name : "Remote"}
              </Badge>
            }
          />
          <CheckInWidget expectedHours={expectedHours} />
        </Card>

        {/* My Requests — replaces the admin layout's "Active Employees" */}
        <Card testId="my-requests-widget">
          <CardHeader
            title="My Requests"
            action={
              <button
                onClick={() => onNavigate?.("leave")}
                className="flex items-center gap-0.5 text-xs font-medium text-[hsl(var(--primary))] hover:underline"
              >
                View all
                <ChevronRight size={13} />
              </button>
            }
          />
          {requestsQuery.isLoading ? (
            <SkeletonList rows={4} height="h-[52px]" />
          ) : (requestsQuery.data?.length ?? 0) === 0 ? (
            <EmptyState
              icon={<Umbrella size={20} />}
              title="No requests yet"
              body="Apply for leave and you'll be able to track its status here."
              action={
                <Button variant="secondary" size="sm" onClick={() => onNavigate?.("leave")}>
                  Request leave
                </Button>
              }
            />
          ) : (
            <ul className="flex flex-col gap-1.5">
              {requestsQuery.data?.slice(0, 5).map((r) => (
                <li
                  key={r.id}
                  className="flex items-center gap-3 rounded-[var(--radius-control)] bg-[hsl(var(--row))] px-3.5 py-2.5"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-[hsl(var(--primary))]">
                      {r.leave_type}
                    </span>
                    <span className="block truncate text-xs text-[hsl(var(--foreground-muted))]">
                      {formatDate(r.start_date)} – {formatDate(r.end_date)} · {r.total_days} day
                      {r.total_days === 1 ? "" : "s"}
                    </span>
                  </span>
                  <Badge
                    variant={r.status === "approved" ? "success" : r.status === "rejected" ? "error" : "warning"}
                  >
                    {r.status === "pending" ? "Pending" : r.status === "approved" ? "Approved" : "Declined"}
                  </Badge>
                </li>
              ))}
            </ul>
          )}

          {/* Leave balance meter — kept under the requests list rather
              than as its own card, since "how many days do I have left"
              is the question you ask while looking at your requests. */}
          <LeaveBalanceList />
        </Card>
      </div>

      {/* ── Public holidays ──────────────────────────────────────────── */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-heading text-base font-semibold tracking-tight text-[hsl(var(--foreground))]">
            Upcoming public holidays
          </h2>
        </div>
        {holidaysQuery.isLoading ? (
          <div className="grid grid-cols-2 gap-[18px] lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[86px] rounded-[var(--radius-card)]" />
            ))}
          </div>
        ) : (holidaysQuery.data?.length ?? 0) === 0 ? (
          <Card testId="upcoming-holidays-widget">
            <EmptyState
              icon={<PartyPopper size={20} />}
              title="No upcoming holidays"
              body="Your organisation hasn't published holidays for the rest of this year yet."
            />
          </Card>
        ) : (
          <div data-testid="upcoming-holidays-widget" className="grid grid-cols-2 gap-[18px] lg:grid-cols-4">
            {holidaysQuery.data?.slice(0, 4).map((h, i) => (
              <div
                key={h.id}
                className={cn(
                  "rounded-[var(--radius-card)] bg-[hsl(var(--card))] p-4 text-center",
                  i === 0 && "outline outline-2 -outline-offset-2 outline-[hsl(var(--primary))]",
                )}
              >
                <p className="num font-heading text-base font-semibold text-[hsl(var(--foreground))]">
                  {formatDate(h.date)}
                </p>
                <p className="mt-0.5 truncate text-xs text-[hsl(var(--primary))]">{h.name}</p>
                {h.is_optional && (
                  <Badge variant="outline" className="mt-2">
                    Optional
                  </Badge>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <button
        data-testid="unread-notifications-pill"
        onClick={() => onNavigate?.("notifications")}
        className="flex items-center justify-between rounded-[var(--radius-card)] bg-[hsl(var(--card))] px-[18px] py-4 text-left text-sm transition-colors hover:bg-[hsl(var(--row))]"
      >
        <span className="flex items-center gap-2.5 text-[hsl(var(--foreground-muted))]">
          <Bell size={15} />
          {unreadQuery.isLoading
            ? "Checking notifications…"
            : `${unreadQuery.data ?? 0} unread notification${unreadQuery.data === 1 ? "" : "s"}`}
        </span>
        <ChevronRight size={15} className="text-[hsl(var(--foreground-muted))]" />
      </button>
    </div>
  );
}

/** Today / this week.
 *
 * Still sourced from workSessionsService (getMyRecentSessions +
 * sumMinutesToday / sumMinutesThisWeek) rather than the month attendance
 * fetch. Those two helpers already handle the hard part — a session that
 * is still running has `total_minutes: null` server-side, so they
 * estimate from started_at minus completed breaks. Recomputing that here
 * from attendance rows would be a worse answer, not a better one.
 *
 * Separate component so the 1s timer tick re-renders only this strip
 * instead of the whole dashboard.
 */
function TodayWeekStrip({ expectedHours }: { expectedHours: number }): JSX.Element {
  const sessionsQuery = useQuery({
    queryKey: ["work-sessions", "me", "recent"],
    queryFn: () => getMyRecentSessions(),
    refetchInterval: 120_000,
  });
  // Subscribed to purely so the card re-renders each second while the
  // clock runs — the value itself comes from the sessions above.
  useTimerStore((s) => s.elapsedSeconds);

  const todayMinutes = sessionsQuery.data ? sumMinutesToday(sessionsQuery.data) : 0;
  const weekMinutes = sessionsQuery.data ? sumMinutesThisWeek(sessionsQuery.data) : 0;
  const expectedTodayMinutes = Math.max(1, expectedHours * 60);
  const expectedWeekMinutes = expectedTodayMinutes * 5;

  return (
    <div className="grid grid-cols-2 gap-[18px]">
      <Card testId="stat-today-hours" className="flex items-center gap-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--secondary))] text-[hsl(var(--primary))]">
          <Clock size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs text-[hsl(var(--foreground-muted))]">Today</p>
          <p className="num font-heading text-xl font-bold tracking-tight text-[hsl(var(--foreground))]">
            {sessionsQuery.isLoading ? "…" : formatHours(todayMinutes)}
          </p>
          <ProgressBar
            className="mt-2"
            segments={[
              {
                key: "worked",
                percent: (Math.min(todayMinutes, expectedTodayMinutes) / expectedTodayMinutes) * 100,
                token: "--primary",
              },
              {
                key: "ot",
                percent: (Math.max(0, todayMinutes - expectedTodayMinutes) / expectedTodayMinutes) * 100,
                token: "--warning",
              },
            ]}
          />
        </div>
      </Card>

      <Card testId="stat-week-hours" className="flex items-center gap-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--secondary))] text-[hsl(var(--primary))]">
          <CalendarRange size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs text-[hsl(var(--foreground-muted))]">This week</p>
          <p className="num font-heading text-xl font-bold tracking-tight text-[hsl(var(--foreground))]">
            {sessionsQuery.isLoading ? "…" : formatHours(weekMinutes)}
          </p>
          <ProgressBar
            className="mt-2"
            segments={[
              { key: "worked", percent: (weekMinutes / expectedWeekMinutes) * 100, token: "--primary" },
            ]}
          />
        </div>
      </Card>
    </div>
  );
}

/** Per-leave-type balance, listed by name.
 *
 * A single merged "18.5 days left" number is useless the moment an org
 * has more than one leave type — you cannot tell whether those are
 * vacation days or sick days, and they are not interchangeable. */
function LeaveBalanceList(): JSX.Element {
  const balancesQuery = useQuery({ queryKey: ["leave", "balances"], queryFn: () => getMyLeaveBalances() });
  const balances = balancesQuery.data ?? [];

  return (
    <div data-testid="leave-balance-widget" className="mt-4 border-t border-[hsl(var(--border))] pt-3.5">
      <p className="mb-2 text-xs font-semibold text-[hsl(var(--foreground-muted))]">Leave balance</p>
      {balancesQuery.isLoading ? (
        <SkeletonList rows={2} height="h-5" />
      ) : balances.length === 0 ? (
        <p className="text-xs text-[hsl(var(--foreground-muted))]">No leave types configured.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {balances.map((b) => {
            const total = Math.max(b.entitled_days + b.carried_forward_days, 1);
            return (
              <li key={b.leave_type_id}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2 text-xs text-[hsl(var(--foreground))]">
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: b.leave_type_color }}
                      aria-hidden
                    />
                    <span className="truncate">{b.leave_type_name}</span>
                  </span>
                  <span className="num shrink-0 text-xs font-semibold text-[hsl(var(--primary))]">
                    {b.remaining_days}
                    <span className="ml-1 font-normal text-[hsl(var(--foreground-muted))]">days left</span>
                  </span>
                </div>
                <ProgressBar
                  className="mt-1.5 h-1.5"
                  segments={[
                    { key: "used", percent: (b.used_days / total) * 100, token: "--primary" },
                    { key: "pending", percent: (b.pending_days / total) * 100, token: "--warning" },
                  ]}
                />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** One check-in/check-out pair in the Daily Reports timeline. A small
 * connector rail on the left (dot + line) is what makes several of these
 * read as "the shape of the day" rather than a plain stacked list — the
 * same idea as the week ribbon, just for one day at session grain. */
function SessionRow({ session, isLast }: { session: WorkSessionItem; isLast: boolean }): JSX.Element {
  const isOpen = session.status !== "ended";
  const minutes = effectiveSessionMinutes(session);

  const stateLabel =
    session.status === "on_break" ? "On break" : session.status === "active" ? "In progress" : "Completed";
  const dotColor = session.status === "on_break" ? "orange" : session.status === "active" ? "green" : "gray";

  return (
    <li className="flex gap-3">
      <div className="flex flex-col items-center pt-1">
        <StatusDot color={dotColor} pulse={session.status === "active"} />
        {!isLast && <span aria-hidden className="mt-1 w-px flex-1 bg-[hsl(var(--border))]" />}
      </div>
      <div className={cn("min-w-0 flex-1 pb-3", isLast && "pb-0.5")}>
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <span className="flex items-baseline gap-1.5 text-sm">
            <span className="num font-semibold text-[hsl(var(--foreground))]">
              {formatClockTime(session.started_at)}
            </span>
            <span className="text-[hsl(var(--foreground-muted))]">→</span>
            <span
              className={cn(
                "num font-semibold",
                isOpen ? "text-[hsl(var(--success))]" : "text-[hsl(var(--foreground))]",
              )}
            >
              {session.ended_at ? formatClockTime(session.ended_at) : stateLabel}
            </span>
          </span>
          <span className="num text-xs font-medium text-[hsl(var(--foreground-muted))]">
            {formatHours(minutes)}
          </span>
        </div>
      </div>
    </li>
  );
}

function RowStat({ label, value, tone }: { label: string; value: string; tone?: string }): JSX.Element {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs text-[hsl(var(--foreground-muted))]">{label}</dt>
      <dd className={cn("num text-sm font-semibold text-[hsl(var(--foreground))]", tone)}>{value}</dd>
    </div>
  );
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

function balanceLabel(worked: number, required: number): string {
  if (!required) return "—";
  const diff = worked - required;
  if (Math.abs(diff) < 30) return "On target";
  return diff > 0 ? `${formatHours(diff)} ahead` : `${formatHours(-diff)} to go`;
}

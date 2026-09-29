import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, CheckCircle2, Plus, History, CalendarOff } from "lucide-react";
import { applyForLeave, getMyLeaveBalances, getMyLeaveRequests, listLeaveTypes } from "../services/leaveService";
import { getUpcomingHolidays } from "../services/holidaysService";
import { listShifts, pickDefaultShift } from "../services/shiftsService";
import type { LeaveApplyPayload, LeaveRequestStatus } from "../types/hrms";
import { countWorkingDays, formatDate, toIsoDate } from "../lib/format";
import {
  Badge, Button, Card, CardHeader, EmptyState, Field, ProgressBar,
  SkeletonList, cn, inputClass,
} from "../components/ui";

/**
 * Leave — apply and history.
 *
 * The headline addition is the COST PREVIEW above the submit button: how
 * many working days the request actually consumes once weekends (per the
 * org's shift work_days) and public holidays are removed. That number is
 * the single thing people most often get wrong when booking leave, and
 * every endpoint needed to compute it was already available — /holidays
 * and /shifts — it just was not being used.
 *
 * The preview is explicitly labelled as an estimate. The backend does its
 * own calculation on submit and that one wins; this exists so nobody is
 * surprised by the result, not to replace it.
 */

const STATUS_VARIANT: Record<LeaveRequestStatus, "warning" | "success" | "error"> = {
  pending: "warning",
  approved: "success",
  rejected: "error",
};

export default function LeaveScreen(): JSX.Element {
  const [tab, setTab] = useState<"apply" | "history">("apply");

  return (
    <div className="flex w-full flex-col gap-[18px] p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-[22px] font-semibold tracking-tight text-[hsl(var(--foreground))]">
            Leave
          </h1>
          <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
            Book time off and track where each request stands
          </p>
        </div>
        <div className="flex gap-1 rounded-[var(--radius-control)] bg-[hsl(var(--muted))] p-1">
          {(
            [
              { id: "apply", label: "Apply", icon: <Plus size={14} /> },
              { id: "history", label: "History", icon: <History size={14} /> },
            ] as const
          ).map((t) => (
            <button
              key={t.id}
              data-testid={`leave-tab-${t.id}`}
              onClick={() => setTab(t.id)}
              className={cn(
                "flex items-center gap-1.5 rounded-[var(--radius-chip)] px-4 py-1.5 text-xs font-semibold transition-colors",
                tab === t.id
                  ? "bg-[hsl(var(--card))] text-[hsl(var(--primary))] shadow-[var(--shadow-xs)]"
                  : "text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]",
              )}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>
      </header>

      <BalanceStrip />

      {tab === "apply" ? <ApplyLeaveForm /> : <LeaveHistory />}
    </div>
  );
}

/** Per-leave-type balance cards. Previously this was a plain <li> list on
 * the dashboard with one number each; here each type gets its own card
 * with the full four-number breakdown, which is what people check before
 * deciding what to book. */
function BalanceStrip(): JSX.Element {
  const balancesQuery = useQuery({ queryKey: ["leave", "balances"], queryFn: () => getMyLeaveBalances() });

  if (balancesQuery.isLoading) {
    return (
      <div className="grid grid-cols-2 gap-[18px] lg:grid-cols-4">
        <SkeletonList rows={1} height="h-[104px]" />
        <SkeletonList rows={1} height="h-[104px]" />
        <SkeletonList rows={1} height="h-[104px]" />
        <SkeletonList rows={1} height="h-[104px]" />
      </div>
    );
  }

  // Deliberately no empty-state card here. An empty balances list can
  // mean "no leave types configured" but just as easily means "leave
  // types exist but nobody has set this employee's entitlement yet" —
  // the leave-type dropdown below queries a different endpoint
  // (listLeaveTypes) and can be populated even when this is empty, so a
  // card blaming "no leave categories" would actively contradict the
  // working dropdown right underneath it. Silently render nothing and
  // let the apply form speak for itself.
  if ((balancesQuery.data?.length ?? 0) === 0) {
    return <div data-testid="leave-balance-widget" />;
  }

  return (
    <div data-testid="leave-balance-widget" className="grid grid-cols-2 gap-[18px] lg:grid-cols-4">
      {balancesQuery.data?.map((b) => {
        const total = Math.max(b.entitled_days + b.carried_forward_days, 1);
        return (
          <Card key={b.leave_type_id}>
            <div className="flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: b.leave_type_color }}
                aria-hidden
              />
              <p className="truncate text-xs font-medium text-[hsl(var(--foreground-muted))]">{b.leave_type_name}</p>
            </div>
            <p className="num mt-1 font-heading text-[26px] font-bold leading-tight tracking-tight text-[hsl(var(--foreground))]">
              {b.remaining_days}
              <span className="ml-1 text-sm font-medium text-[hsl(var(--foreground-muted))]">left</span>
            </p>
            <ProgressBar
              className="mt-2.5"
              segments={[
                { key: "used", percent: (b.used_days / total) * 100, token: "--primary" },
                { key: "pending", percent: (b.pending_days / total) * 100, token: "--warning" },
              ]}
            />
            <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-[hsl(var(--foreground-muted))]">
              <span>{b.used_days} used</span>
              {b.pending_days > 0 && <span>{b.pending_days} pending</span>}
              <span>{b.entitled_days + b.carried_forward_days} total</span>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function ApplyLeaveForm(): JSX.Element {
  const queryClient = useQueryClient();
  const typesQuery = useQuery({ queryKey: ["leave", "types"], queryFn: listLeaveTypes });
  const balancesQuery = useQuery({ queryKey: ["leave", "balances"], queryFn: () => getMyLeaveBalances() });
  const holidaysQuery = useQuery({ queryKey: ["holidays", "upcoming"], queryFn: getUpcomingHolidays });
  const shiftsQuery = useQuery({ queryKey: ["shifts"], queryFn: listShifts, staleTime: 60 * 60 * 1000 });

  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [startDate, setStartDate] = useState(toIsoDate(new Date()));
  const [endDate, setEndDate] = useState(toIsoDate(new Date()));
  const [durationType, setDurationType] = useState<LeaveApplyPayload["duration_type"]>("full_day");
  const [halfDayPeriod, setHalfDayPeriod] = useState<"morning" | "afternoon">("morning");
  const [hours, setHours] = useState(4);
  const [reason, setReason] = useState("");
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: applyForLeave,
    onSuccess: () => {
      setSuccessMsg("Leave request submitted.");
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["leave"] });
    },
  });

  const selectedType = typesQuery.data?.find((t) => t.id === leaveTypeId);
  const selectedBalance = balancesQuery.data?.find((b) => b.leave_type_id === leaveTypeId);
  const shift = pickDefaultShift(shiftsQuery.data);

  // Working-day cost, weekends and public holidays excluded. Recomputed
  // only when the inputs that matter change — this walks day by day, so
  // it must not run on every keystroke in the reason box.
  const cost = useMemo(() => {
    if (durationType === "half_day") return 0.5;
    if (durationType === "hourly") return Math.round((hours / 8) * 100) / 100;
    const from = new Date(`${startDate}T00:00:00`);
    const to = new Date(`${endDate}T00:00:00`);
    if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime()) || to < from) return 0;
    const holidayDates = new Set((holidaysQuery.data ?? []).filter((h) => !h.is_optional).map((h) => h.date));
    return countWorkingDays(from, to, shift?.work_days ?? null, holidayDates);
  }, [durationType, hours, startDate, endDate, holidaysQuery.data, shift]);

  // The specific holidays being skipped, named. "4 days, not 5" is only
  // trustworthy if it says WHICH day it dropped.
  const skippedHolidays = useMemo(() => {
    if (durationType !== "full_day") return [];
    return (holidaysQuery.data ?? []).filter(
      (h) => !h.is_optional && h.date >= startDate && h.date <= endDate,
    );
  }, [holidaysQuery.data, startDate, endDate, durationType]);

  const exceedsBalance = !!selectedBalance && cost > selectedBalance.remaining_days;

  function handleSubmit(e: React.FormEvent): void {
    e.preventDefault();
    setSuccessMsg(null);
    if (!leaveTypeId) return;

    const payload: LeaveApplyPayload = {
      leave_type_id: leaveTypeId,
      start_date: startDate,
      end_date: durationType === "full_day" ? endDate : startDate,
      duration_type: durationType,
      reason: reason || undefined,
      ...(durationType === "half_day" ? { half_day_period: halfDayPeriod } : {}),
      ...(durationType === "hourly" ? { hours } : {}),
    };
    mutation.mutate(payload);
  }

  return (
    <Card className="max-w-[640px]">
      <CardHeader title="Request time off" />
      <form data-testid="leave-apply-form" onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        <Field label="Leave type">
          <select
            data-testid="leave-type-select"
            value={leaveTypeId}
            onChange={(e) => setLeaveTypeId(e.target.value)}
            required
            className={inputClass}
          >
            <option value="">Select…</option>
            {typesQuery.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>

        {selectedBalance && (
          <p data-testid="selected-type-balance" className="-mt-1 text-xs text-[hsl(var(--foreground-muted))]">
            {selectedBalance.remaining_days} day(s) remaining
            {selectedType?.requires_approval ? " · requires approval" : ""}
            {selectedType?.requires_document ? " · document required" : ""}
          </p>
        )}

        <Field label="Duration">
          <select
            value={durationType}
            onChange={(e) => setDurationType(e.target.value as LeaveApplyPayload["duration_type"])}
            className={inputClass}
          >
            <option value="full_day">Full day(s)</option>
            <option value="half_day">Half day</option>
            <option value="hourly">Hourly</option>
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Start date">
            <input
              type="date"
              value={startDate}
              onChange={(e) => {
                setStartDate(e.target.value);
                if (e.target.value > endDate) setEndDate(e.target.value);
              }}
              required
              className={inputClass}
            />
          </Field>
          {durationType === "full_day" && (
            <Field label="End date">
              <input
                type="date"
                value={endDate}
                min={startDate}
                onChange={(e) => setEndDate(e.target.value)}
                required
                className={inputClass}
              />
            </Field>
          )}
          {durationType === "half_day" && (
            <Field label="Period">
              <select
                value={halfDayPeriod}
                onChange={(e) => setHalfDayPeriod(e.target.value as "morning" | "afternoon")}
                className={inputClass}
              >
                <option value="morning">Morning</option>
                <option value="afternoon">Afternoon</option>
              </select>
            </Field>
          )}
          {durationType === "hourly" && (
            <Field label="Hours">
              <input
                type="number"
                min={1}
                max={8}
                value={hours}
                onChange={(e) => setHours(Number(e.target.value))}
                required
                className={inputClass}
              />
            </Field>
          )}
        </div>

        <Field label="Reason (optional)">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            placeholder="Anything your approver should know"
            className={cn(inputClass, "resize-none")}
          />
        </Field>

        {/* Cost preview — the loudest thing in the form, directly above
            the submit button, because it is the last thing that should be
            read before committing. */}
        <div
          data-testid="leave-cost-preview"
          className="rounded-[var(--radius-card)] bg-[hsl(var(--primary))] px-4 py-3.5 text-[hsl(var(--primary-foreground))]"
        >
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm text-white/80">This request costs</span>
            <span className="num font-heading text-2xl font-bold tracking-tight">
              {cost} day{cost === 1 ? "" : "s"}
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-white/70">
            {durationType === "full_day"
              ? skippedHolidays.length > 0
                ? `Weekends excluded, and ${skippedHolidays.map((h) => `${formatDate(h.date)} (${h.name})`).join(", ")} skipped as a public holiday.`
                : "Weekends and public holidays excluded."
              : "Counted against your balance as a part-day."}
            {selectedBalance && ` ${Math.round((selectedBalance.remaining_days - cost) * 10) / 10} day(s) would remain.`}
          </p>
          <p className="mt-1.5 text-[10px] text-white/50">
            Estimated here — your organisation&apos;s own calculation applies on approval.
          </p>
        </div>

        {exceedsBalance && (
          <p role="alert" className="text-xs font-medium text-[hsl(var(--status-warning-fg))]">
            This is {Math.round((cost - (selectedBalance?.remaining_days ?? 0)) * 10) / 10} day(s) more than you have
            left. You can still send it — your approver decides whether a negative balance is allowed.
          </p>
        )}

        <Button
          type="submit"
          data-testid="leave-submit-button"
          disabled={mutation.isPending || !leaveTypeId}
          size="lg"
        >
          {mutation.isPending && <Loader2 size={15} className="animate-spin" />}
          Send request
        </Button>

        {successMsg && (
          <p
            data-testid="leave-success-message"
            className="flex items-center gap-1.5 text-xs font-medium text-[hsl(var(--success))]"
          >
            <CheckCircle2 size={14} />
            {successMsg}
          </p>
        )}
        {mutation.isError && (
          <p role="alert" className="text-xs text-[hsl(var(--destructive))]">
            {(mutation.error as { response?: { data?: { detail?: string; message?: string } } })?.response?.data
              ?.detail ??
              (mutation.error as { response?: { data?: { message?: string } } })?.response?.data?.message ??
              "Could not submit this request. Check the dates and try again."}
          </p>
        )}
      </form>
    </Card>
  );
}

function LeaveHistory(): JSX.Element {
  const requestsQuery = useQuery({ queryKey: ["leave", "requests"], queryFn: () => getMyLeaveRequests() });

  if (requestsQuery.isLoading) {
    return <SkeletonList rows={4} height="h-20" />;
  }

  if ((requestsQuery.data?.length ?? 0) === 0) {
    return (
      <Card>
        <EmptyState
          icon={<CalendarOff size={20} />}
          title="No requests yet"
          body="Requests you send will appear here with their status, so you can see what's still waiting on an approver."
        />
      </Card>
    );
  }

  return (
    <ul data-testid="leave-history-list" className="flex flex-col gap-2.5">
      {requestsQuery.data?.map((r) => (
        <li key={r.id}>
          <Card className="flex items-start gap-4">
            <span
              className="mt-1 h-9 w-1 shrink-0 rounded-full"
              style={{ backgroundColor: r.leave_type_color }}
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-semibold text-[hsl(var(--foreground))]">{r.leave_type}</span>
                <Badge variant={STATUS_VARIANT[r.status]} className="capitalize">
                  {r.status}
                </Badge>
              </div>
              <p className="num mt-1 text-xs text-[hsl(var(--foreground-muted))]">
                {formatDate(r.start_date)} – {formatDate(r.end_date)} · {r.total_days} day
                {r.total_days === 1 ? "" : "s"}
                {r.duration_type === "half_day" && r.half_day_period ? ` · ${r.half_day_period}` : ""}
                {r.duration_type === "hourly" && r.hours ? ` · ${r.hours}h` : ""}
              </p>
              {r.reason && (
                <p className="mt-1.5 text-xs leading-relaxed text-[hsl(var(--foreground-subtle))]">{r.reason}</p>
              )}
            </div>
          </Card>
        </li>
      ))}
    </ul>
  );
}

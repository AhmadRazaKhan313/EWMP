import { useQuery } from "@tanstack/react-query";
import { getMyAttendance } from "../services/attendanceService";
import { getMyLeaveBalances } from "../services/leaveService";
import { getUpcomingHolidays } from "../services/holidaysService";
import { listShifts, pickDefaultShift, dailyHoursForShift } from "../services/shiftsService";
import { countWorkingDays, endOfMonth, startOfMonth } from "../lib/format";

/**
 * Assembles the four figures in the dashboard's indigo stat band.
 *
 * There is no single backend endpoint for this. `GET /dashboard/stats`
 * exists but returns ORG-WIDE ADMIN counts (total employees, open
 * tickets, devices online) — nothing scoped to "me". So this composes
 * four self-scoped endpoints that do exist:
 *
 *   /leave/balances  → vacation entitled / used / remaining
 *   /attendance      → actual worked + overtime minutes this month
 *   /shifts          → the working pattern behind "required hours"
 *   /holidays        → days that must NOT count toward required hours
 *
 * All four queries run in parallel; the band renders per-cell as each
 * lands rather than blocking on the slowest.
 *
 * On `requiredMinutes` specifically — this is DERIVED, not fetched:
 *   working days in month (excluding weekends per the shift's own
 *   work_days, and excluding public holidays) × the shift's daily paid
 *   hours (span minus unpaid break).
 * It is the only figure here the backend cannot confirm. See
 * shiftsService.pickDefaultShift for why it can be wrong in a
 * multi-shift org, and `isRequiredDerived` below for how the UI is
 * expected to label it.
 */
export interface MonthSummary {
  vacationEntitledDays: number;
  vacationUsedDays: number;
  vacationPendingDays: number;
  vacationRemainingDays: number;
  vacationCarriedDays: number;
  requiredMinutes: number;
  workedMinutes: number;
  overtimeMinutes: number;
  lateMinutes: number;
  workingDaysInMonth: number;
  daysPresent: number;
  /** True whenever requiredMinutes came from the derivation above rather
   * than a server figure — always true today. Kept explicit so the day a
   * real endpoint lands, the UI's caveat disappears on its own. */
  isRequiredDerived: boolean;
  isLoading: boolean;
  isError: boolean;
}

export function useMonthSummary(month: Date = new Date()): MonthSummary {
  const monthKey = `${month.getFullYear()}-${month.getMonth()}`;

  const attendanceQuery = useQuery({
    queryKey: ["attendance", "month", monthKey],
    queryFn: () =>
      getMyAttendance({
        from: startOfMonth(month),
        to: endOfMonth(month),
      }),
  });
  const balancesQuery = useQuery({
    queryKey: ["leave", "balances"],
    queryFn: () => getMyLeaveBalances(),
  });
  const holidaysQuery = useQuery({
    queryKey: ["holidays", "upcoming"],
    queryFn: getUpcomingHolidays,
  });
  const shiftsQuery = useQuery({
    queryKey: ["shifts"],
    // Org-wide config that changes maybe twice a year — no point
    // refetching it on every window focus.
    staleTime: 60 * 60 * 1000,
    queryFn: listShifts,
  });

  const records = attendanceQuery.data ?? [];
  const workedMinutes = records.reduce((sum, r) => sum + (r.total_minutes ?? 0), 0);
  const overtimeMinutes = records.reduce((sum, r) => sum + (r.overtime_minutes ?? 0), 0);
  const lateMinutes = records.reduce((sum, r) => sum + (r.late_minutes ?? 0), 0);
  const daysPresent = records.filter(
    (r) => r.status === "present" || r.status === "late" || r.status === "work_from_home" || r.status === "half_day",
  ).length;

  // Every leave type summed, not just "Annual" — orgs name their vacation
  // type differently (Annual / Paid Time Off / Earned Leave), and
  // string-matching on the name would break the moment someone renames it.
  const balances = balancesQuery.data ?? [];
  const vacationEntitledDays = balances.reduce((s, b) => s + (b.entitled_days ?? 0), 0);
  const vacationCarriedDays = balances.reduce((s, b) => s + (b.carried_forward_days ?? 0), 0);
  const vacationUsedDays = balances.reduce((s, b) => s + (b.used_days ?? 0), 0);
  const vacationPendingDays = balances.reduce((s, b) => s + (b.pending_days ?? 0), 0);
  const vacationRemainingDays = balances.reduce((s, b) => s + (b.remaining_days ?? 0), 0);

  const shift = pickDefaultShift(shiftsQuery.data);
  const holidayDates = new Set((holidaysQuery.data ?? []).filter((h) => !h.is_optional).map((h) => h.date));
  const workingDaysInMonth = countWorkingDays(
    startOfMonth(month),
    endOfMonth(month),
    shift?.work_days ?? null,
    holidayDates,
  );
  const requiredMinutes = Math.round(workingDaysInMonth * dailyHoursForShift(shift) * 60);

  return {
    vacationEntitledDays,
    vacationCarriedDays,
    vacationUsedDays,
    vacationPendingDays,
    vacationRemainingDays,
    requiredMinutes,
    workedMinutes,
    overtimeMinutes,
    lateMinutes,
    workingDaysInMonth,
    daysPresent,
    isRequiredDerived: true,
    isLoading: attendanceQuery.isLoading || balancesQuery.isLoading,
    isError: attendanceQuery.isError,
  };
}

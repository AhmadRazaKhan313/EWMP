import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getMyLeaveBalances, listLeaveTypes } from "../services/leaveService";
import type { LeaveBalanceItem } from "../types/hrms";

/** How long the loading skeleton may show before the cards give up and
 * either render what they have or disappear. A slow or hung request must
 * never leave a skeleton on screen indefinitely. */
const SKELETON_MAX_MS = 4000;

/**
 * The leave-balance cards, with a guaranteed end to their loading state.
 *
 * Source order:
 *  1. GET /leave/balances — the real per-employee numbers.
 *  2. GET /leave/types — when (1) is empty or refused (it needs the
 *     `leave.view` permission, which a plain employee may not hold), each
 *     active leave type becomes a card showing its yearly entitlement with
 *     nothing used. That is exactly what the backend itself reports for an
 *     employee who has not touched a type this year.
 *  3. Neither has anything: no cards at all (`items` is empty and
 *     `isLoading` is false) — never a permanent skeleton.
 *
 * Both queries use retry: false so a refused request settles at once
 * instead of retrying behind a skeleton.
 */
export function useLeaveBalanceCards(): { items: LeaveBalanceItem[]; isLoading: boolean } {
  const balances = useQuery({
    queryKey: ["leave", "balances"],
    queryFn: () => getMyLeaveBalances(),
    retry: false,
  });
  const types = useQuery({
    queryKey: ["leave", "types"],
    queryFn: listLeaveTypes,
    retry: false,
  });

  const [timedOut, setTimedOut] = useState(false);
  const pending = balances.isLoading || (balances.data?.length === 0 || balances.isError ? types.isLoading : false);
  useEffect(() => {
    if (!pending) return;
    const id = window.setTimeout(() => setTimedOut(true), SKELETON_MAX_MS);
    return () => window.clearTimeout(id);
  }, [pending]);

  if (balances.data && balances.data.length > 0) {
    return { items: balances.data, isLoading: false };
  }

  const year = new Date().getFullYear();
  const fromTypes: LeaveBalanceItem[] = (types.data ?? []).map((t) => {
    const entitled = Number.parseFloat(t.days_per_year);
    const days = Number.isFinite(entitled) ? entitled : 0;
    return {
      leave_type_id: t.id,
      leave_type_name: t.name,
      leave_type_color: t.color,
      year,
      entitled_days: days,
      carried_forward_days: 0,
      used_days: 0,
      pending_days: 0,
      remaining_days: days,
    };
  });

  return { items: fromTypes, isLoading: pending && !timedOut };
}

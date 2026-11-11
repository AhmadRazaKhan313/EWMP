import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "./api-client";
import { apiErrorMessage } from "./payroll.service";

export type BudgetPeriod = "week" | "month" | "year";
export const PERIOD_LABEL: Record<BudgetPeriod, string> = { week: "Weekly", month: "Monthly", year: "Yearly" };
export const SAVED_LABEL: Record<BudgetPeriod, string> = { week: "week", month: "month", year: "year" };

export interface BudgetRow { category: string; planned: string; actual: string; diff: string }
export interface BudgetSection { planned: string; actual: string; diff: string; rows: BudgetRow[] }
export interface Budget {
  period: BudgetPeriod; start: string; end: string; label: string;
  starting_balance: string; starting_balance_manual: boolean; end_balance: string; saved: string;
  expenses: BudgetSection; income: BudgetSection;
}

const pad = (n: number) => String(n).padStart(2, "0");
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** The date one week / month / year before (-1) or after (+1) `date` (YYYY-MM-DD). Months never overflow (31 Jan + 1 month = 28/29 Feb). */
export function shiftDate(period: BudgetPeriod, date: string, dir: 1 | -1): string {
  const [y, m, d] = date.split("-").map(Number) as [number, number, number];
  if (period === "week") return ymd(new Date(y, m - 1, d + 7 * dir));
  const months = period === "month" ? dir : 12 * dir;
  const total = y * 12 + (m - 1) + months;
  const ny = Math.floor(total / 12), nm = total % 12;
  return ymd(new Date(ny, nm, Math.min(d, new Date(ny, nm + 1, 0).getDate())));
}
export const today = () => ymd(new Date());

export const budgetKeys = { all: ["finance", "budget"] as const, one: (p: BudgetPeriod, d: string) => ["finance", "budget", p, d] as const };

export function useBudget(period: BudgetPeriod, date: string) {
  return useQuery({
    queryKey: budgetKeys.one(period, date),
    queryFn: async () => (await apiClient.get<Budget>("/finance/budget", { params: { period, date } })).data,
  });
}

function mut<TVars>(fn: (v: TVars) => Promise<unknown>, fail: string) {
  return () => {
    const qc = useQueryClient();
    return useMutation({
      mutationFn: fn,
      onSuccess: () => { void qc.invalidateQueries({ queryKey: budgetKeys.all }); },
      onError: (e: unknown) => toast.error(apiErrorMessage(e, fail)),
    });
  };
}

export interface PlanVars { period: BudgetPeriod; date: string; kind: "income" | "expense"; category: string; planned: string }
export const useSetPlan = mut((v: PlanVars) => apiClient.put("/finance/budget/plan", v), "Could not save the planned amount");

export interface OpeningVars { period: BudgetPeriod; date: string; starting_balance: string | null }
export const useSetOpening = mut((v: OpeningVars) => apiClient.put("/finance/budget/opening", v), "Could not save the starting balance");

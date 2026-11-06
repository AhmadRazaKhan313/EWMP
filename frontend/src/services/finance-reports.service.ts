import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "./api-client";
import { apiErrorMessage } from "./payroll.service";

export type Preset = "this_month" | "last_month" | "this_quarter" | "this_year" | "last_year" | "this_fy" | "custom";
export const PRESET_LABEL: Record<Preset, string> = {
  this_month: "This month", last_month: "Last month", this_quarter: "This quarter", this_year: "This year",
  last_year: "Last year", this_fy: "This financial year", custom: "Custom",
};

const pad = (n: number) => String(n).padStart(2, "0");
export const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const end = (y: number, m: number) => new Date(y, m + 1, 0); // last day of month m (0-based)

/** Date range for a preset. The financial year runs July to June. */
export function presetRange(p: Exclude<Preset, "custom">, today = new Date()): { from: string; to: string } {
  const y = today.getFullYear(), m = today.getMonth();
  switch (p) {
    case "this_month": return { from: ymd(new Date(y, m, 1)), to: ymd(end(y, m)) };
    case "last_month": return { from: ymd(new Date(y, m - 1, 1)), to: ymd(end(y, m - 1)) };
    case "this_quarter": { const q = Math.floor(m / 3) * 3; return { from: ymd(new Date(y, q, 1)), to: ymd(end(y, q + 2)) }; }
    case "this_year": return { from: `${y}-01-01`, to: `${y}-12-31` };
    case "last_year": return { from: `${y - 1}-01-01`, to: `${y - 1}-12-31` };
    case "this_fy": { const s = m >= 6 ? y : y - 1; return { from: `${s}-07-01`, to: `${s + 1}-06-30` }; }
  }
}

export interface PLRow { account_id: string; code: string; name: string; amount: string; previous?: string }
export interface PLSection { rows: PLRow[]; total: string; previous_total?: string }
export interface ProfitLoss {
  currency: string; date_from: string; date_to: string; income: PLSection; expenses: PLSection; net_profit: string;
  previous_from?: string; previous_to?: string; previous_net_profit?: string;
}
export interface BSRow { account_id: string; code: string; name: string; amount: string }
export interface BalanceSheet {
  currency: string; as_of: string; assets: { rows: BSRow[]; total: string }; liabilities: { rows: BSRow[]; total: string };
  equity: { rows: BSRow[]; profit_to_date: string; total: string }; liabilities_and_equity: string; balanced: boolean;
}
export interface TrialBalance {
  accounts: { account_id: string; code: string; name: string; type: string; debit: string; credit: string }[];
  total_debit: string; total_credit: string; balanced: boolean; as_of: string | null;
}
export type Bucket = "current" | "d1_30" | "d31_60" | "d61_90" | "d90_plus";
export const BUCKETS: { key: Bucket; label: string }[] = [
  { key: "current", label: "Current" }, { key: "d1_30", label: "1–30" }, { key: "d31_60", label: "31–60" },
  { key: "d61_90", label: "61–90" }, { key: "d90_plus", label: "90+" },
];
export interface AgingRow extends Record<Bucket, string> { party_id: string; name: string; total: string; items: { number: string; due_date: string; days_overdue: number; balance: string }[] }
export interface Aging { currency: string; as_of: string; rows: AgingRow[]; totals: Record<Bucket | "total", string> }
export interface GLLine { date: string; number: string; entry_id: string; memo: string | null; reference: string | null; description: string | null; debit: string; credit: string; balance: string }
export interface GeneralLedger {
  currency: string; account: { id: string; code: string; name: string; type: string }; opening_balance: string; closing_balance: string;
  total_debit: string; total_credit: string; lines: GLLine[]; truncated: boolean;
}

const get = async <T,>(url: string, params?: Record<string, unknown>) => (await apiClient.get<T>(url, { params })).data;
const key = (name: string, p: unknown) => ["finance", "reports", name, p] as const;

export function useProfitLoss(p: { date_from: string; date_to: string; compare: boolean }, enabled = true) {
  return useQuery({ queryKey: key("pl", p), enabled, queryFn: () => get<ProfitLoss>("/finance/reports/profit-loss", p) });
}
export function useBalanceSheet(as_of: string, enabled = true) {
  return useQuery({ queryKey: key("bs", as_of), enabled, queryFn: () => get<BalanceSheet>("/finance/reports/balance-sheet", { as_of }) });
}
export function useTrialBalanceReport(as_of: string, enabled = true) {
  return useQuery({ queryKey: key("tb", as_of), enabled, queryFn: () => get<TrialBalance>("/finance/trial-balance", { as_of }) });
}
export function useAging(kind: "receivables" | "payables", enabled = true) {
  return useQuery({ queryKey: key("aging", kind), enabled, queryFn: () => get<Aging>(`/finance/reports/${kind}-aging`) });
}
export function useGeneralLedger(p: { account_id: string; date_from: string; date_to: string }, enabled = true) {
  return useQuery({ queryKey: key("gl", p), enabled: enabled && !!p.account_id, queryFn: () => get<GeneralLedger>("/finance/reports/general-ledger", p) });
}

export type ReportName = "profit-loss" | "balance-sheet" | "trial-balance" | "receivables-aging" | "payables-aging" | "general-ledger";

export async function exportReport(report: ReportName, format: "xlsx" | "csv", params: Record<string, unknown>): Promise<void> {
  try {
    const { data } = await apiClient.get<Blob>("/finance/reports/export", { params: { report, format, ...params }, responseType: "blob" });
    const url = URL.createObjectURL(data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${report}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    toast.error(apiErrorMessage(e, "Could not export the report"));
  }
}

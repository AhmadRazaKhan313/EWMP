import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "./api-client";
import { apiErrorMessage } from "./payroll.service";
import { financeKeys } from "./finance.service";

export type LineStatus = "unmatched" | "matched" | "ignored";

export interface BankLine {
  id: string; statement_id: string; account_id: string; date: string; description: string | null; reference: string | null;
  amount: string; balance: string | null; status: LineStatus; reconciled: boolean;
  match: { entry_line_id: string; entry_id: string; number: string; date: string; memo: string | null; voided: boolean } | null;
}
export interface BankLines { items: BankLine[]; total: number; counts: Record<LineStatus, number> }
export interface Suggestion { entry_line_id: string; entry_id: string; number: string; date: string; memo: string | null; reference: string | null; payment_tid: string | null; amount: string }
export interface StatementImportResult {
  dry_run: boolean; total_rows: number; to_import: number; imported: number; duplicates: number; matched: number; statement_id: string | null;
  date_order: "mdy" | "dmy"; date_order_guessed: boolean; skipped: { row: number; reason: string }[];
  preview: { date: string; description: string | null; reference: string | null; amount: string; duplicate: boolean }[];
}
export interface ReconcileCheck {
  account_id: string; statement_date: string; beginning_balance: string; beginning_from_last: boolean; statement_balance: string; cleared_total: string;
  cleared_count: number; unmatched_count: number; difference: string; ledger_balance: string; can_finish: boolean; reason: string | null;
}
export interface Reconciliation { id: string; account_id: string; statement_date: string; beginning_balance: string; statement_balance: string; cleared_total: string; line_count: number; created_at: string }
export interface ReconcileVars { account_id: string; statement_date: string; statement_balance: string; beginning_balance?: string }

export const bankKeys = {
  all: ["finance", "banking"] as const,
  lines: (account: string, status: string, q: string) => ["finance", "banking", "lines", account, status, q] as const,
  recs: (account: string) => ["finance", "banking", "recs", account] as const,
  suggestions: (line: string) => ["finance", "banking", "suggestions", line] as const,
};

export function useBankLines(accountId: string, status: LineStatus | "", q: string) {
  return useQuery({
    queryKey: bankKeys.lines(accountId, status, q),
    enabled: !!accountId,
    queryFn: async () => (await apiClient.get<BankLines>("/finance/banking/lines", {
      params: { account_id: accountId, ...(status ? { status } : {}), ...(q ? { q } : {}), limit: 500 },
    })).data,
  });
}

export function useSuggestions(lineId: string) {
  return useQuery({
    queryKey: bankKeys.suggestions(lineId),
    queryFn: async () => (await apiClient.get<{ items: Suggestion[] }>(`/finance/banking/lines/${lineId}/suggestions`)).data.items,
  });
}

export function useReconciliations(accountId: string) {
  return useQuery({
    queryKey: bankKeys.recs(accountId),
    enabled: !!accountId,
    queryFn: async () => (await apiClient.get<{ items: Reconciliation[] }>("/finance/banking/reconciliations", { params: { account_id: accountId } })).data.items,
  });
}

function mut<TVars, TRes>(fn: (v: TVars) => Promise<TRes>, ok: string | ((r: TRes) => string) | null, fail: string) {
  return () => {
    const qc = useQueryClient();
    return useMutation({
      mutationFn: fn,
      onSuccess: (res) => {
        if (ok) toast.success(typeof ok === "function" ? ok(res) : ok);
        void qc.invalidateQueries({ queryKey: bankKeys.all });
        void qc.invalidateQueries({ queryKey: financeKeys.all });
      },
      onError: (e: unknown) => toast.error(apiErrorMessage(e, fail)),
    });
  };
}

const post = <T,>(url: string, body?: unknown) => apiClient.post<T>(url, body ?? {}).then((r) => r.data);

export const useAutoMatch = mut((accountId: string) => post<{ matched: number }>(`/finance/banking/accounts/${accountId}/auto-match`),
  (r) => (r.matched ? `${r.matched} line${r.matched === 1 ? "" : "s"} matched` : "Nothing new to match"), "Could not match");
export const useMatchLine = mut((v: { lineId: string; entryLineId: string }) => post(`/finance/banking/lines/${v.lineId}/match`, { entry_line_id: v.entryLineId }),
  "Matched", "Could not match the line");
export const useUnmatchLine = mut((lineId: string) => post(`/finance/banking/lines/${lineId}/unmatch`), "Match removed", "Could not remove the match");
export const useIgnoreLine = mut((lineId: string) => post(`/finance/banking/lines/${lineId}/ignore`), "Line ignored", "Could not ignore the line");
export const useRestoreLine = mut((lineId: string) => post(`/finance/banking/lines/${lineId}/restore`), "Line restored", "Could not restore the line");

export interface BookVars { lineId: string; type: "income" | "expense" | "transfer"; category_id?: string; other_account_id?: string; description?: string }
export const useBookLine = mut(({ lineId, ...body }: BookVars) => post<{ number: string }>(`/finance/banking/lines/${lineId}/create-entry`, body),
  (r) => `Booked as ${r.number} and matched`, "Could not book the line");

export const useFinishReconciliation = mut((v: ReconcileVars) => post<Reconciliation>("/finance/banking/reconciliations", v), "Reconciliation finished", "Could not finish the reconciliation");
export const useUndoReconciliation = mut((id: string) => apiClient.delete(`/finance/banking/reconciliations/${id}`).then((r) => r.data), "Reconciliation undone", "Could not undo the reconciliation");

export async function checkReconciliation(v: ReconcileVars): Promise<ReconcileCheck> {
  return (await apiClient.post<ReconcileCheck>("/finance/banking/reconciliations/preview", v)).data;
}

export async function importStatement(args: { file: File; accountId: string; dryRun: boolean; dateOrder?: "mdy" | "dmy" }): Promise<StatementImportResult> {
  const form = new FormData();
  form.append("file", args.file);
  form.append("account_id", args.accountId);
  form.append("dry_run", String(args.dryRun));
  if (args.dateOrder) form.append("date_order", args.dateOrder);
  return (await apiClient.post<StatementImportResult>("/finance/banking/statements/import", form)).data;
}

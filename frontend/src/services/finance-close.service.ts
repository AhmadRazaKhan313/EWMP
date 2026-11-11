import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "./api-client";
import { apiErrorMessage } from "./payroll.service";
import { financeKeys } from "./finance.service";

export type CloseKind = "month" | "year";
export interface PeriodClose { id: string; period_type: CloseKind; period_start: string; period_end: string; net_profit: string; note: string | null; closed_at: string | null }
export interface CloseStatus {
  locked_through: string | null; closes: PeriodClose[];
  suggested: { period_type: CloseKind; period_start: string; period_end: string; label: string } | null;
}
export interface ClosePreview {
  period_type: CloseKind; period_start: string; period_end: string; label: string; income: string; expenses: string; net_profit: string;
  draft_invoices: number; draft_bills: number; pending_approval: number; unmatched_bank_lines: number;
  blockers: string[]; warnings: string[]; can_close: boolean;
}
export interface OpeningItem { account_id: string; code: string; name: string; type: string; amount: string }
export interface OpeningBalances { as_of: string | null; entry_number: string | null; items: OpeningItem[]; balancing: string }

export const closeKeys = {
  all: ["finance", "close"] as const,
  preview: (k: string, d: string) => ["finance", "close", "preview", k, d] as const,
  opening: ["finance", "close", "opening"] as const,
};

export const useCloseStatus = () => useQuery({
  queryKey: [...closeKeys.all, "status"], queryFn: async () => (await apiClient.get<CloseStatus>("/finance/close")).data,
});

export function useClosePreview(kind: CloseKind, date: string) {
  return useQuery({
    queryKey: closeKeys.preview(kind, date), enabled: !!date,
    queryFn: async () => (await apiClient.get<ClosePreview>("/finance/close/preview", { params: { period_type: kind, date } })).data,
  });
}

export const useOpeningBalances = () => useQuery({
  queryKey: closeKeys.opening, queryFn: async () => (await apiClient.get<OpeningBalances>("/finance/opening-balances")).data,
});

function mut<TVars, TRes>(fn: (v: TVars) => Promise<TRes>, ok: string, fail: string) {
  return () => {
    const qc = useQueryClient();
    return useMutation({
      mutationFn: fn,
      onSuccess: () => {
        toast.success(ok);
        void qc.invalidateQueries({ queryKey: closeKeys.all });
        void qc.invalidateQueries({ queryKey: financeKeys.all });
      },
      onError: (e: unknown) => toast.error(apiErrorMessage(e, fail)),
    });
  };
}

export const useClosePeriod = mut((v: { period_type: CloseKind; date: string; note?: string }) =>
  apiClient.post<PeriodClose>("/finance/close", v).then((r) => r.data), "Period closed", "Could not close the period");
export const useReopenPeriod = mut<void, PeriodClose>(() => apiClient.post<PeriodClose>("/finance/close/reopen", {}).then((r) => r.data), "Period reopened", "Could not reopen the period");
export const useSaveOpening = mut((v: { as_of: string; items: { account_id: string; amount: string }[] }) =>
  apiClient.put<OpeningBalances>("/finance/opening-balances", v).then((r) => r.data), "Opening balances saved", "Could not save the opening balances");
export const useClearOpening = mut<void, unknown>(() => apiClient.delete("/finance/opening-balances").then((r) => r.data), "Opening balances removed", "Could not remove the opening balances");

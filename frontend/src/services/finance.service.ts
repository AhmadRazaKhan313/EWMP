import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "./api-client";
import { apiErrorMessage } from "./payroll.service";

export type TxnType = "income" | "expense" | "transfer";
export type MoneyKind = "cash" | "bank" | "wallet";
export type AccountType = "asset" | "liability" | "equity" | "income" | "expense";

export interface FinAccount {
  id: string;
  code: string;
  name: string;
  type: AccountType;
  parent_id: string | null;
  is_system: boolean;
  is_active: boolean;
  money_kind?: MoneyKind | null;
}

export interface FinTransaction {
  id: string;
  number: string;
  type: TxnType;
  date: string;
  amount: string;
  currency: string;
  description: string | null;
  account_id: string;
  account: string;
  category_id: string;
  category: string;
  category_type: AccountType;
  account_kind?: MoneyKind | null;
  payment_provider?: string | null;
  payment_account_no?: string | null;
  payment_tid?: string | null;
}

export interface CategoryTotal {
  category_id: string;
  category: string;
  type: AccountType;
  total: string;
}

export interface FinSummary {
  currency: string;
  income_total: string;
  income_operating: string;
  income_financing: string;
  expense_total: string;
  balance: string;
  profit: string;
  income_by_category: CategoryTotal[];
  expense_by_category: CategoryTotal[];
  money_accounts: { account_id: string; code: string; name: string; balance: string }[];
}

export interface ImportPreview {
  dry_run: boolean;
  total_rows: number;
  to_import: number;
  imported: number;
  duplicates: number;
  date_order: "mdy" | "dmy";
  skipped: { row: number; reason: string }[];
  new_categories: string[];
  preview: { row: number; date: string; amount: string; description: string | null; category: string }[];
}

export const financeKeys = {
  all: ["finance"] as const,
  accounts: () => [...financeKeys.all, "accounts"] as const,
  summary: () => [...financeKeys.all, "summary"] as const,
  txns: (type: TxnType | undefined, categoryId: string | undefined) => [...financeKeys.all, "txns", type ?? "all", categoryId ?? "all"] as const,
};

// Header rows of the default chart and the non-cash assets: not valid "where did the money go" picks.
const HEADER_CODES = ["1000", "2000", "3000", "4000", "5000"];
const NON_MONEY_ASSETS = ["1000", "1100", "1200", "1500"];

export const isMoneyAccount = (a: FinAccount) => a.type === "asset" && !NON_MONEY_ASSETS.includes(a.code);

/** Categories the Add-entry form may offer for a transaction type (mirrors the backend rule). */
export function categoriesFor(accounts: FinAccount[], type: TxnType): FinAccount[] {
  if (type === "transfer") return [];
  const ok: AccountType[] = type === "income" ? ["income", "equity", "liability"] : ["expense", "asset", "liability"];
  return accounts.filter(
    (a) => ok.includes(a.type) && !HEADER_CODES.includes(a.code) && !(a.type === "asset" && a.code !== "1500"),
  );
}

export function formatMoney(amount: string | number, currency = "PKR"): string {
  const n = typeof amount === "number" ? amount : parseFloat(amount);
  try {
    return new Intl.NumberFormat("en-PK", { style: "currency", currency, maximumFractionDigits: 2 }).format(n);
  } catch {
    return `${currency} ${n.toLocaleString("en-US")}`;
  }
}

export function useFinAccounts() {
  return useQuery({
    queryKey: financeKeys.accounts(),
    queryFn: async () => (await apiClient.get<{ items: FinAccount[] }>("/finance/accounts")).data.items,
  });
}

export function useFinSummary() {
  return useQuery({
    queryKey: financeKeys.summary(),
    queryFn: async () => (await apiClient.get<FinSummary>("/finance/summary")).data,
  });
}

export function useFinTransactions(type: TxnType | undefined, categoryId?: string) {
  return useQuery({
    queryKey: financeKeys.txns(type, categoryId),
    queryFn: async () =>
      (await apiClient.get<{ items: FinTransaction[]; total: number }>("/finance/transactions", {
        params: { type, category_id: categoryId, page_size: 500 },
      })).data,
    enabled: type !== undefined,
  });
}

function useRefresh() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: financeKeys.all });
}

export function useSetupFinance() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async () => (await apiClient.post("/finance/setup")).data,
    onSuccess: () => { toast.success("Finance is ready"); void refresh(); },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Could not set up finance")),
  });
}

export interface NewTransaction {
  type: TxnType;
  date: string;
  amount: string;
  account_id: string;
  category_id?: string;
  to_account_id?: string;
  description?: string;
  payment_provider?: string;
  payment_account_no?: string;
  payment_tid?: string;
}

export function useCreateTransaction() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (body: NewTransaction) => (await apiClient.post<FinTransaction>("/finance/transactions", body)).data,
    onSuccess: () => { toast.success("Entry added"); void refresh(); },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Could not add the entry")),
  });
}

export function useVoidTransaction() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (id: string) => (await apiClient.post(`/finance/journal/${id}/void`, { reason: "Voided from the Finance page" })).data,
    onSuccess: () => { toast.success("Entry voided"); void refresh(); },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Could not void the entry")),
  });
}

/** Creates a money account or a category; the server picks the next free code. */
export function useCreateAccount() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (body: { name: string; type: AccountType; money_kind?: MoneyKind }) => (await apiClient.post<FinAccount>("/finance/accounts", body)).data,
    onSuccess: () => { void refresh(); },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Could not create the account")),
  });
}

/** Banks or mobile wallets to pick from: the built-in list plus the ones this organization added. */
export function useProviders(kind: "bank" | "wallet" | undefined) {
  return useQuery({
    queryKey: [...financeKeys.all, "providers", kind ?? "none"] as const,
    queryFn: async () => (await apiClient.get<{ items: string[] }>("/finance/providers", { params: { kind } })).data.items,
    enabled: kind !== undefined,
  });
}

export function useAddProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { kind: "bank" | "wallet"; name: string }) => (await apiClient.post<{ items: string[] }>("/finance/providers", body)).data,
    onSuccess: (_d, v) => { void qc.invalidateQueries({ queryKey: [...financeKeys.all, "providers", v.kind] }); },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Could not add the name")),
  });
}

export async function importTransactions(args: {
  file: File;
  type: "income" | "expense";
  accountId: string;
  dryRun: boolean;
  dateOrder?: "mdy" | "dmy";
}): Promise<ImportPreview> {
  const form = new FormData();
  form.append("file", args.file);
  form.append("type", args.type);
  form.append("account_id", args.accountId);
  form.append("dry_run", String(args.dryRun));
  if (args.dateOrder) form.append("date_order", args.dateOrder);
  return (await apiClient.post<ImportPreview>("/finance/transactions/import", form)).data;
}

export async function downloadFinanceExcel(): Promise<void> {
  try {
    const response = await apiClient.get("/finance/transactions/export", { responseType: "blob" });
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement("a");
    link.href = url;
    link.download = "finance.xlsx";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    toast.error(apiErrorMessage(err, "Could not download the file"));
  }
}

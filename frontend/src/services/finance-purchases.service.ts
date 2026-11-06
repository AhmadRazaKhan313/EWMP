import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "./api-client";
import { apiErrorMessage } from "./payroll.service";
import { financeKeys, type FinAccount } from "./finance.service";
import { type Frequency } from "./finance-sales.service";

export type BillStatus = "draft" | "open" | "partially_paid" | "paid" | "void";

export interface Vendor {
  id: string; name: string; company: string | null; email: string | null; phone: string | null; address: string | null;
  currency: string | null; payment_terms_days: number; notes: string | null; is_active: boolean; balance?: string;
}

export interface BillLine {
  id?: string; description: string; quantity: string; unit_price: string; discount_percent: string;
  tax_rate_id: string | null; expense_account_id: string | null;
}

export interface Bill {
  id: string; number: string; vendor_id: string; vendor_name: string | null; vendor_ref: string | null; status: BillStatus;
  is_overdue: boolean; issue_date: string; due_date: string; currency: string; exchange_rate: string; subtotal: string;
  tax_total: string; total: string; amount_paid: string; balance: string; notes: string | null;
  approval_status: "none" | "pending" | "approved" | "rejected"; rejection_reason: string | null; recurring_id: string | null;
}

export interface BillPayment {
  id: string; number: string; vendor_id: string; vendor_name: string | null; status: "posted" | "void"; payment_date: string;
  amount: string; currency: string; unapplied: string; allocations: { bill_id: string; bill_number: string; amount: string }[];
}

export type BillFilter = BillStatus | "overdue" | undefined;

export const purchaseKeys = {
  all: ["finance", "purchases"] as const,
  vendors: () => [...purchaseKeys.all, "vendors"] as const,
  bills: (s: BillFilter) => [...purchaseKeys.all, "bills", s ?? "all"] as const,
  payments: () => [...purchaseKeys.all, "payments"] as const,
  orders: () => [...purchaseKeys.all, "orders"] as const,
  recurring: () => [...purchaseKeys.all, "recurring"] as const,
  settings: () => [...purchaseKeys.all, "settings"] as const,
  attachments: (billId: string) => [...purchaseKeys.all, "attachments", billId] as const,
};

export const BILL_LABEL: Record<BillStatus | "overdue", string> = {
  draft: "Draft", open: "Open", partially_paid: "Partially paid", paid: "Paid", void: "Void", overdue: "Overdue",
};

/** Accounts a bill line may post to: expenses and fixed assets (mirrors the server). */
export function billAccounts(accounts: FinAccount[]): FinAccount[] {
  const headers = ["5000"];
  return accounts.filter((a) => a.is_active && !headers.includes(a.code) && (a.type === "expense" || a.code === "1500"));
}

export function useVendors() {
  return useQuery({
    queryKey: purchaseKeys.vendors(),
    queryFn: async () => (await apiClient.get<{ items: Vendor[] }>("/finance/vendors")).data.items,
  });
}

export function useBills(status: BillFilter) {
  return useQuery({
    queryKey: purchaseKeys.bills(status),
    queryFn: async () => (await apiClient.get<{ items: Bill[]; total: number }>("/finance/bills", { params: { status, page_size: 200 } })).data,
  });
}

export function useBillPayments() {
  return useQuery({
    queryKey: purchaseKeys.payments(),
    queryFn: async () => (await apiClient.get<{ items: BillPayment[]; total: number }>("/finance/bill-payments", { params: { page_size: 200 } })).data,
  });
}

export async function fetchOpenBills(vendorId: string): Promise<Bill[]> {
  const out: Bill[] = [];
  for (const status of ["open", "partially_paid"] as const) {
    const { data } = await apiClient.get<{ items: Bill[] }>("/finance/bills", { params: { status, vendor_id: vendorId, page_size: 200 } });
    out.push(...data.items);
  }
  return out.sort((a, b) => a.due_date.localeCompare(b.due_date));
}

function mut<TVars, TRes>(fn: (v: TVars) => Promise<TRes>, ok: string, fail: string) {
  return () => {
    const qc = useQueryClient();
    return useMutation({
      mutationFn: fn,
      onSuccess: () => {
        toast.success(ok);
        void qc.invalidateQueries({ queryKey: purchaseKeys.all });
        void qc.invalidateQueries({ queryKey: financeKeys.all });
      },
      onError: (e: unknown) => toast.error(apiErrorMessage(e, fail)),
    });
  };
}

export type NewVendor = Partial<Omit<Vendor, "id" | "balance" | "is_active">> & { name: string };
export const useCreateVendor = mut((b: NewVendor) => apiClient.post<Vendor>("/finance/vendors", b).then((r) => r.data), "Vendor added", "Could not add the vendor");

export interface NewBill {
  vendor_id: string; issue_date: string; due_date?: string; currency?: string; rate?: string; vendor_ref?: string;
  notes?: string; post: boolean;
  lines: { description: string; quantity: string; unit_price: string; discount_percent: string; tax_rate_id?: string; expense_account_id?: string }[];
}
export const useCreateBill = mut((b: NewBill) => apiClient.post<Bill>("/finance/bills", b).then((r) => r.data), "Bill saved", "Could not save the bill");
export const usePostBill = mut((id: string) => apiClient.post(`/finance/bills/${id}/post`).then((r) => r.data), "Bill posted", "Could not post the bill");
export const useVoidBill = mut((id: string) => apiClient.post(`/finance/bills/${id}/void`, {}).then((r) => r.data), "Bill voided", "Could not void the bill");
export const useDeleteBill = mut((id: string) => apiClient.delete(`/finance/bills/${id}`).then((r) => r.data), "Draft deleted", "Could not delete the draft");

export interface NewBillPayment {
  vendor_id: string; payment_date: string; amount: string; paid_from_account_id: string; currency?: string; rate?: string;
  allocations: { bill_id: string; amount: string }[];
}
export const useCreateBillPayment = mut((b: NewBillPayment) => apiClient.post<BillPayment>("/finance/bill-payments", b).then((r) => r.data), "Payment recorded", "Could not record the payment");
export const useVoidBillPayment = mut((id: string) => apiClient.post(`/finance/bill-payments/${id}/void`, {}).then((r) => r.data), "Payment voided", "Could not void the payment");

// ───────── Phase 3b: approvals ─────────
export function useApprovalLimit() {
  return useQuery({
    queryKey: purchaseKeys.settings(),
    queryFn: async () => {
      const v = (await apiClient.get<{ approval_threshold: string | null }>("/finance/purchase-settings")).data.approval_threshold;
      return v === null ? null : parseFloat(v);
    },
  });
}
export const useSetApprovalLimit = mut((limit: string | null) => apiClient.put("/finance/purchase-settings", { approval_threshold: limit }).then((r) => r.data), "Approval limit saved", "Could not save the approval limit");
export const useRequestApproval = mut((id: string) => apiClient.post(`/finance/bills/${id}/request-approval`).then((r) => r.data), "Approval requested", "Could not request approval");
export const useApproveBill = mut((id: string) => apiClient.post(`/finance/bills/${id}/approve`).then((r) => r.data), "Bill approved and posted", "Could not approve the bill");
export const useRejectBill = mut((v: { id: string; reason: string }) => apiClient.post(`/finance/bills/${v.id}/reject`, { reason: v.reason }).then((r) => r.data), "Bill rejected", "Could not reject the bill");

/** True when the bill (in base currency) reaches the approval limit. */
export function needsApproval(b: Pick<Bill, "total" | "exchange_rate">, limit: number | null | undefined): boolean {
  return limit != null && parseFloat(b.total) * parseFloat(b.exchange_rate) >= limit;
}

// ───────── Phase 3b: attachments ─────────
export interface BillAttachment { id: string; file_name: string; mime_type: string; size_bytes: number; uploaded_at: string | null }
export function useAttachments(billId: string) {
  return useQuery({
    queryKey: purchaseKeys.attachments(billId),
    queryFn: async () => (await apiClient.get<{ items: BillAttachment[] }>(`/finance/bills/${billId}/attachments`)).data.items,
  });
}
export const useUploadAttachment = mut((v: { billId: string; file: File }) => {
  const fd = new FormData();
  fd.append("file", v.file);
  return apiClient.post(`/finance/bills/${v.billId}/attachments`, fd).then((r) => r.data);
}, "File attached", "Could not attach the file");
export const useDeleteAttachment = mut((v: { billId: string; id: string }) => apiClient.delete(`/finance/bills/${v.billId}/attachments/${v.id}`).then((r) => r.data), "File removed", "Could not remove the file");

export async function downloadAttachment(billId: string, a: BillAttachment): Promise<void> {
  const { data } = await apiClient.get<Blob>(`/finance/bills/${billId}/attachments/${a.id}`, { responseType: "blob" });
  const url = URL.createObjectURL(data);
  const link = document.createElement("a");
  link.href = url;
  link.download = a.file_name;
  link.click();
  URL.revokeObjectURL(url);
}

// ───────── Phase 3b: purchase orders ─────────
export type OrderStatus = "draft" | "sent" | "received" | "billed" | "cancelled";
export const ORDER_LABEL: Record<OrderStatus, string> = { draft: "Draft", sent: "Sent", received: "Received", billed: "Billed", cancelled: "Cancelled" };
export interface PurchaseOrder {
  id: string; number: string; vendor_id: string; vendor_name: string | null; status: OrderStatus; issue_date: string;
  expected_date: string | null; currency: string; subtotal: string; tax_total: string; total: string;
  reference: string | null; notes: string | null; bill_id: string | null;
}
export function usePurchaseOrders() {
  return useQuery({
    queryKey: purchaseKeys.orders(),
    queryFn: async () => (await apiClient.get<{ items: PurchaseOrder[] }>("/finance/purchase-orders", { params: { page_size: 200 } })).data.items,
  });
}
export interface NewOrder {
  vendor_id: string; issue_date: string; expected_date?: string; currency?: string; notes?: string; send: boolean;
  lines: NewBill["lines"];
}
export const useCreateOrder = mut((b: NewOrder) => apiClient.post<PurchaseOrder>("/finance/purchase-orders", b).then((r) => r.data), "Purchase order saved", "Could not save the purchase order");
export const useOrderAction = mut((v: { id: string; action: "sent" | "received" | "cancelled" }) => apiClient.post(`/finance/purchase-orders/${v.id}/${v.action}`).then((r) => r.data), "Purchase order updated", "Could not update the purchase order");
export const useConvertOrder = mut((id: string) => apiClient.post(`/finance/purchase-orders/${id}/convert`, {}).then((r) => r.data), "Draft bill created from the order", "Could not create the bill");
export const useDeleteOrder = mut((id: string) => apiClient.delete(`/finance/purchase-orders/${id}`).then((r) => r.data), "Draft deleted", "Could not delete the order");

// ───────── Phase 3b: recurring bills ─────────
export interface RecurringBill {
  id: string; title: string; vendor_id: string; vendor_name: string | null; status: "active" | "paused" | "ended";
  frequency: Frequency; start_date: string; end_date: string | null; next_run_date: string; run_count: number;
  auto_post: boolean; currency: string; last_error: string | null;
}
export function useRecurringBills() {
  return useQuery({
    queryKey: purchaseKeys.recurring(),
    queryFn: async () => (await apiClient.get<{ items: RecurringBill[] }>("/finance/recurring-bills")).data.items,
  });
}
export interface NewRecurringBill {
  title: string; vendor_id: string; frequency: Frequency; start_date: string; end_date?: string; auto_post: boolean; lines: NewBill["lines"];
}
export const useCreateRecurringBill = mut((b: NewRecurringBill) => apiClient.post<RecurringBill>("/finance/recurring-bills", b).then((r) => r.data), "Schedule saved", "Could not save the schedule");
export const useRecurringBillAction = mut((v: { id: string; action: "pause" | "resume" }) => apiClient.post(`/finance/recurring-bills/${v.id}/${v.action}`).then((r) => r.data), "Schedule updated", "Could not update the schedule");
export const useDeleteRecurringBill = mut((id: string) => apiClient.delete(`/finance/recurring-bills/${id}`).then((r) => r.data), "Schedule deleted", "Could not delete the schedule");
export const useRunRecurringBills = mut(
  (_: void) => apiClient.post<{ created: number; failed: unknown[] }>("/finance/recurring-bills/run").then((r) => r.data),
  "Due bills created", "Could not create the due bills",
);

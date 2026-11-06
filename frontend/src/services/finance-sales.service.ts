import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "./api-client";
import { apiErrorMessage } from "./payroll.service";
import { financeKeys } from "./finance.service";

export type InvoiceStatus = "draft" | "sent" | "partially_paid" | "paid" | "void";

export interface Customer {
  id: string; name: string; company: string | null; email: string | null; phone: string | null;
  address: string | null; currency: string | null; payment_terms_days: number; notes: string | null;
  is_active: boolean; balance?: string; auto_remind?: boolean;
}

export interface InvoiceLine {
  id?: string; description: string; quantity: string; unit_price: string; discount_percent: string;
  tax_rate_id: string | null; income_account_id?: string; net_amount?: string; tax_amount?: string;
}

export interface Invoice {
  id: string; number: string; customer_id: string; customer_name: string | null; status: InvoiceStatus;
  is_overdue: boolean; issue_date: string; due_date: string; currency: string; exchange_rate: string;
  subtotal: string; tax_total: string; total: string; amount_paid: string; balance: string;
  reference: string | null; notes: string | null; lines?: InvoiceLine[];
  reminder_count?: number; last_reminded_at?: string | null; recurring_id?: string | null;
}

export interface Payment {
  id: string; number: string; customer_id: string; customer_name: string | null; status: "posted" | "void";
  payment_date: string; amount: string; currency: string; method: string | null; reference: string | null;
  unapplied: string; allocations: { invoice_id: string; invoice_number: string; amount: string }[];
}

export interface TaxRate { id: string; name: string; percent: string; is_active: boolean }

export type InvoiceFilter = InvoiceStatus | "overdue" | undefined;

export const salesKeys = {
  all: ["finance", "sales"] as const,
  customers: () => [...salesKeys.all, "customers"] as const,
  invoices: (status: InvoiceFilter) => [...salesKeys.all, "invoices", status ?? "all"] as const,
  payments: () => [...salesKeys.all, "payments"] as const,
  taxes: () => [...salesKeys.all, "taxes"] as const,
};

/** Line total as the server computes it (quantity x price less discount), shown live in the form. */
export function lineNet(l: Pick<InvoiceLine, "quantity" | "unit_price" | "discount_percent">): number {
  const n = parseFloat(l.quantity) * parseFloat(l.unit_price) * (1 - (parseFloat(l.discount_percent || "0") || 0) / 100);
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0;
}

export const STATUS_LABEL: Record<InvoiceStatus | "overdue", string> = {
  draft: "Draft", sent: "Sent", partially_paid: "Partially paid", paid: "Paid", void: "Void", overdue: "Overdue",
};

export function useCustomers() {
  return useQuery({
    queryKey: salesKeys.customers(),
    queryFn: async () => (await apiClient.get<{ items: Customer[] }>("/finance/customers")).data.items,
  });
}

export function useInvoices(status: InvoiceFilter) {
  return useQuery({
    queryKey: salesKeys.invoices(status),
    queryFn: async () =>
      (await apiClient.get<{ items: Invoice[]; total: number }>("/finance/invoices", { params: { status, page_size: 200 } })).data,
  });
}

export function usePayments() {
  return useQuery({
    queryKey: salesKeys.payments(),
    queryFn: async () => (await apiClient.get<{ items: Payment[]; total: number }>("/finance/payments", { params: { page_size: 200 } })).data,
  });
}

export function useTaxRates() {
  return useQuery({
    queryKey: salesKeys.taxes(),
    queryFn: async () => (await apiClient.get<{ items: TaxRate[] }>("/finance/tax-rates")).data.items.filter((t) => t.is_active),
  });
}

export async function fetchOpenInvoices(customerId: string): Promise<Invoice[]> {
  const out: Invoice[] = [];
  for (const status of ["sent", "partially_paid"] as const) {
    const { data } = await apiClient.get<{ items: Invoice[] }>("/finance/invoices", { params: { status, customer_id: customerId, page_size: 200 } });
    out.push(...data.items);
  }
  return out.sort((a, b) => a.due_date.localeCompare(b.due_date));
}

function useRefresh() {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: salesKeys.all }), qc.invalidateQueries({ queryKey: financeKeys.all })]);
}

function mut<TVars, TRes>(fn: (v: TVars) => Promise<TRes>, ok: string, fail: string) {
  return () => {
    const refresh = useRefresh();
    return useMutation({
      mutationFn: fn,
      onSuccess: () => { toast.success(ok); void refresh(); },
      onError: (e: unknown) => toast.error(apiErrorMessage(e, fail)),
    });
  };
}

export type NewCustomer = Partial<Omit<Customer, "id" | "balance" | "is_active">> & { name: string };
export const useCreateCustomer = mut((b: NewCustomer) => apiClient.post<Customer>("/finance/customers", b).then((r) => r.data), "Customer added", "Could not add the customer");

export interface NewInvoice {
  customer_id: string; issue_date: string; due_date?: string; currency?: string; rate?: string;
  reference?: string; notes?: string; send: boolean;
  lines: { description: string; quantity: string; unit_price: string; discount_percent: string; tax_rate_id?: string }[];
}
export const useCreateInvoice = mut((b: NewInvoice) => apiClient.post<Invoice>("/finance/invoices", b).then((r) => r.data), "Invoice saved", "Could not save the invoice");
export const useSendInvoice = mut((id: string) => apiClient.post(`/finance/invoices/${id}/send`).then((r) => r.data), "Invoice sent", "Could not send the invoice");
export const useVoidInvoice = mut((id: string) => apiClient.post(`/finance/invoices/${id}/void`, {}).then((r) => r.data), "Invoice voided", "Could not void the invoice");
export const useDeleteInvoice = mut((id: string) => apiClient.delete(`/finance/invoices/${id}`).then((r) => r.data), "Draft deleted", "Could not delete the draft");

export interface NewPayment {
  customer_id: string; payment_date: string; amount: string; deposit_account_id: string; currency?: string;
  rate?: string; method?: string; reference?: string; allocations: { invoice_id: string; amount: string }[];
}
export const useCreatePayment = mut((b: NewPayment) => apiClient.post<Payment>("/finance/payments", b).then((r) => r.data), "Payment recorded", "Could not record the payment");
export const useVoidPayment = mut((id: string) => apiClient.post(`/finance/payments/${id}/void`, {}).then((r) => r.data), "Payment voided", "Could not void the payment");

// ── quotes (Phase 2b) ──
export type QuoteStatus = "draft" | "sent" | "accepted" | "declined" | "invoiced";
export interface Quote {
  id: string; number: string; customer_id: string; customer_name: string | null; status: QuoteStatus; is_expired: boolean;
  issue_date: string; valid_until: string; currency: string; subtotal: string; tax_total: string; total: string;
  reference: string | null; notes: string | null; invoice_id: string | null;
}
export const QUOTE_LABEL: Record<QuoteStatus | "expired", string> = {
  draft: "Draft", sent: "Sent", accepted: "Accepted", declined: "Declined", invoiced: "Invoiced", expired: "Expired",
};
export const quoteKey = (status: string | undefined) => [...salesKeys.all, "quotes", status ?? "all"] as const;

export function useQuotes(status: QuoteStatus | "expired" | undefined) {
  return useQuery({
    queryKey: quoteKey(status),
    queryFn: async () => (await apiClient.get<{ items: Quote[]; total: number }>("/finance/quotes", { params: { status, page_size: 200 } })).data,
  });
}

export interface NewQuote {
  customer_id: string; issue_date: string; valid_until?: string; currency?: string; notes?: string; send: boolean;
  lines: { description: string; quantity: string; unit_price: string; discount_percent: string; tax_rate_id?: string }[];
}
export const useCreateQuote = mut((b: NewQuote) => apiClient.post<Quote>("/finance/quotes", b).then((r) => r.data), "Quote saved", "Could not save the quote");
export const useQuoteAction = mut(
  (v: { id: string; action: "send" | "accept" | "decline" }) => apiClient.post(`/finance/quotes/${v.id}/${v.action}`).then((r) => r.data),
  "Quote updated", "Could not update the quote");
export const useConvertQuote = mut((id: string) => apiClient.post(`/finance/quotes/${id}/convert`, {}).then((r) => r.data), "Draft invoice created", "Could not convert the quote");
export const useDeleteQuote = mut((id: string) => apiClient.delete(`/finance/quotes/${id}`).then((r) => r.data), "Draft deleted", "Could not delete the draft");

// ── recurring invoices + reminders (Phase 2c) ──
export type Frequency = "weekly" | "monthly" | "quarterly" | "yearly";
export interface Recurring {
  id: string; title: string; customer_id: string; customer_name: string | null; status: "active" | "paused" | "ended";
  frequency: Frequency; start_date: string; end_date: string | null; next_run_date: string; run_count: number;
  auto_send: boolean; currency: string; last_error: string | null; amount?: string;
}
export const FREQ_LABEL: Record<Frequency, string> = { weekly: "Weekly", monthly: "Monthly", quarterly: "Every 3 months", yearly: "Yearly" };

export function useRecurring() {
  return useQuery({
    queryKey: [...salesKeys.all, "recurring"] as const,
    queryFn: async () => (await apiClient.get<{ items: Recurring[] }>("/finance/recurring")).data.items,
  });
}

export interface NewRecurring {
  title: string; customer_id: string; frequency: Frequency; start_date: string; end_date?: string; auto_send: boolean;
  lines: { description: string; quantity: string; unit_price: string; discount_percent: string; tax_rate_id?: string }[];
}
export const useCreateRecurring = mut((b: NewRecurring) => apiClient.post<Recurring>("/finance/recurring", b).then((r) => r.data), "Schedule saved", "Could not save the schedule");
export const useRecurringAction = mut(
  (v: { id: string; action: "pause" | "resume" }) => apiClient.post(`/finance/recurring/${v.id}/${v.action}`).then((r) => r.data),
  "Schedule updated", "Could not update the schedule");
export const useDeleteRecurring = mut((id: string) => apiClient.delete(`/finance/recurring/${id}`).then((r) => r.data), "Schedule deleted", "Could not delete the schedule");
export const useRunRecurring = mut(
  (_: void) => apiClient.post<{ created: number; failed: { id: string; title: string; error: string }[] }>("/finance/recurring/run").then((r) => r.data),
  "Schedules checked", "Could not run the schedules");
export const useRemindInvoice = mut((id: string) => apiClient.post(`/finance/invoices/${id}/remind`).then((r) => r.data), "Reminder emailed", "Could not send the reminder");

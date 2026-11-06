"use client";

import { useState } from "react";
import { Ban, BellRing, Check, FilePlus2, FileText, Pause, Play, Plus, Repeat, Send, Trash2, Users, Wallet, X } from "lucide-react";
import { Button, Card, EmptyState, PageHeader, Skeleton, Tabs } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { formatMoney, useFinSummary } from "@/services/finance.service";
import {
  FREQ_LABEL, QUOTE_LABEL, STATUS_LABEL, useDeleteRecurring, useRecurring, useRecurringAction, useRemindInvoice, useRunRecurring, useConvertQuote, useCustomers, useDeleteQuote, useQuoteAction, useQuotes, useDeleteInvoice, useInvoices, usePayments, useSendInvoice, useVoidInvoice, useVoidPayment,
  type Invoice, type InvoiceFilter, type Quote,
} from "@/services/finance-sales.service";
import { cn } from "@/utils/cn";
import { CustomerDialog } from "./CustomerDialog";
import { InvoiceDialog } from "./InvoiceDialog";
import { PaymentDialog } from "./PaymentDialog";
import { QuoteDialog } from "./QuoteDialog";
import { RecurringDialog } from "./RecurringDialog";

type Tab = "invoices" | "quotes" | "recurring" | "payments" | "customers";
const FILTERS: { value: InvoiceFilter | "all"; label: string }[] = [
  { value: "all", label: "All" }, { value: "draft", label: "Draft" }, { value: "sent", label: "Sent" },
  { value: "overdue", label: "Overdue" }, { value: "paid", label: "Paid" }, { value: "void", label: "Void" },
];

function Pill({ inv }: { inv: Invoice }) {
  const key = inv.is_overdue ? "overdue" : inv.status;
  const tone = key === "paid" ? "bg-green-100 text-green-800" : key === "overdue" ? "bg-red-100 text-red-800"
    : key === "void" ? "bg-gray-100 text-gray-500 line-through" : key === "draft" ? "bg-gray-100 text-gray-700" : "bg-blue-100 text-blue-800";
  return <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", tone)}>{STATUS_LABEL[key]}</span>;
}

const th = "px-3 py-2 text-left text-xs font-semibold text-[hsl(var(--foreground-muted))]";
const td = "px-3 py-2 text-sm";

export default function SalesPage() {
  const { hasPermission } = useAuthStore();
  const canPost = hasPermission("finance.post");
  const canVoid = hasPermission("finance.void");
  const [tab, setTab] = useState<Tab>("invoices");
  const [filter, setFilter] = useState<InvoiceFilter | "all">("all");
  const [dialog, setDialog] = useState<"invoice" | "quote" | "recurring" | "payment" | "customer" | null>(null);
  const [payFor, setPayFor] = useState<Invoice | undefined>();

  const summary = useFinSummary();
  const base = summary.data?.currency ?? "PKR";
  const invoices = useInvoices(filter === "all" ? undefined : filter);
  const payments = usePayments();
  const customers = useCustomers();
  const send = useSendInvoice();
  const voidInv = useVoidInvoice();
  const del = useDeleteInvoice();
  const voidPay = useVoidPayment();
  const quotes = useQuotes(undefined);
  const quoteAct = useQuoteAction();
  const convert = useConvertQuote();
  const delQuote = useDeleteQuote();
  const recurring = useRecurring();
  const recAct = useRecurringAction();
  const delRec = useDeleteRecurring();
  const runRec = useRunRecurring();
  const remind = useRemindInvoice();

  const openBalance = (customers.data ?? []).reduce((s, c) => s + parseFloat(c.balance ?? "0"), 0);

  return (
    <div className="space-y-6">
      <PageHeader title="Sales"
        action={
          canPost && (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" icon={<Users size={15} />} onClick={() => setDialog("customer")}>Add customer</Button>
              <Button variant="outline" icon={<Wallet size={15} />} onClick={() => { setPayFor(undefined); setDialog("payment"); }}>Record payment</Button>
              <Button variant="outline" icon={<FilePlus2 size={15} />} onClick={() => setDialog("quote")}>New quote</Button>
              <Button icon={<Plus size={15} />} onClick={() => setDialog("invoice")}>New invoice</Button>
            </div>
          )
        } />

      <Card>
        <p className="text-sm text-[hsl(var(--foreground-muted))]">Receivables outstanding</p>
        <p className="mt-1 text-2xl font-semibold" data-testid="stat-receivable">{formatMoney(openBalance, base)}</p>
      </Card>

      <Tabs<Tab> active={tab} onChange={setTab}
        tabs={[{ value: "invoices", label: "Invoices" }, { value: "quotes", label: "Quotes" }, { value: "recurring", label: "Recurring" }, { value: "payments", label: "Payments" }, { value: "customers", label: "Customers" }]} />

      {tab === "invoices" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {FILTERS.map((f) => (
              <button key={f.value} onClick={() => setFilter(f.value)} aria-pressed={filter === f.value}
                className={cn("rounded-full border px-3 py-1 text-sm", filter === f.value ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]" : "border-[hsl(var(--border))]")}>
                {f.label}
              </button>
            ))}
          </div>
          {invoices.isLoading ? <Skeleton className="h-32" /> : (invoices.data?.items.length ?? 0) === 0 ? (
            <EmptyState icon={FileText} title="No invoices" description={canPost ? "Create your first invoice." : "Nothing here yet."} />
          ) : (
            <Card className="overflow-x-auto p-0">
              <table className="w-full">
                <thead><tr><th className={th}>Number</th><th className={th}>Customer</th><th className={th}>Issued</th><th className={th}>Due</th><th className={th}>Status</th><th className={cn(th, "text-right")}>Total</th><th className={cn(th, "text-right")}>Balance</th><th className={th} /></tr></thead>
                <tbody>
                  {invoices.data!.items.map((i) => (
                    <tr key={i.id} className="border-t border-[hsl(var(--border))]">
                      <td className={cn(td, "font-medium")}>{i.number}</td><td className={td}>{i.customer_name}</td>
                      <td className={td}>{i.issue_date}</td><td className={td}>{i.due_date}</td><td className={td}><Pill inv={i} /></td>
                      <td className={cn(td, "text-right")}>{formatMoney(i.total, i.currency)}</td>
                      <td className={cn(td, "text-right font-semibold")}>{formatMoney(i.balance, i.currency)}</td>
                      <td className={cn(td, "whitespace-nowrap text-right")}>
                        {canPost && i.status === "draft" && <button aria-label={`Send ${i.number}`} title="Send" className="p-1" onClick={() => send.mutate(i.id)}><Send size={15} /></button>}
                        {canPost && i.status === "draft" && <button aria-label={`Delete ${i.number}`} title="Delete draft" className="p-1" onClick={() => del.mutate(i.id)}><Trash2 size={15} /></button>}
                        {canPost && i.is_overdue && <button aria-label={`Remind ${i.number}`} title={`Send reminder${i.reminder_count ? ` (sent ${i.reminder_count}x)` : ""}`} className="p-1" onClick={() => remind.mutate(i.id)}><BellRing size={15} /></button>}
                        {canPost && (i.status === "sent" || i.status === "partially_paid") && (
                          <button aria-label={`Record payment for ${i.number}`} title="Record payment" className="p-1" onClick={() => { setPayFor(i); setDialog("payment"); }}><Wallet size={15} /></button>
                        )}
                        {canVoid && i.status === "sent" && <button aria-label={`Void ${i.number}`} title="Void" className="p-1" onClick={() => voidInv.mutate(i.id)}><Ban size={15} /></button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      )}

      {tab === "quotes" && (
        quotes.isLoading ? <Skeleton className="h-32" /> : (quotes.data?.items.length ?? 0) === 0 ? (
          <EmptyState icon={FilePlus2} title="No quotes" description={canPost ? "Create a quote and turn it into an invoice once accepted." : "Nothing here yet."} />
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full">
              <thead><tr><th className={th}>Number</th><th className={th}>Customer</th><th className={th}>Issued</th><th className={th}>Valid until</th><th className={th}>Status</th><th className={cn(th, "text-right")}>Total</th><th className={th} /></tr></thead>
              <tbody>
                {quotes.data!.items.map((q: Quote) => (
                  <tr key={q.id} className="border-t border-[hsl(var(--border))]">
                    <td className={cn(td, "font-medium")}>{q.number}</td><td className={td}>{q.customer_name}</td>
                    <td className={td}>{q.issue_date}</td><td className={td}>{q.valid_until}</td>
                    <td className={td}>{QUOTE_LABEL[q.is_expired ? "expired" : q.status]}</td>
                    <td className={cn(td, "text-right")}>{formatMoney(q.total, q.currency)}</td>
                    <td className={cn(td, "whitespace-nowrap text-right")}>
                      {canPost && q.status === "draft" && <button aria-label={`Mark ${q.number} sent`} title="Mark sent" className="p-1" onClick={() => quoteAct.mutate({ id: q.id, action: "send" })}><Send size={15} /></button>}
                      {canPost && q.status === "draft" && <button aria-label={`Delete ${q.number}`} title="Delete draft" className="p-1" onClick={() => delQuote.mutate(q.id)}><Trash2 size={15} /></button>}
                      {canPost && q.status === "sent" && <button aria-label={`Accept ${q.number}`} title="Accepted" className="p-1" onClick={() => quoteAct.mutate({ id: q.id, action: "accept" })}><Check size={15} /></button>}
                      {canPost && q.status === "sent" && <button aria-label={`Decline ${q.number}`} title="Declined" className="p-1" onClick={() => quoteAct.mutate({ id: q.id, action: "decline" })}><X size={15} /></button>}
                      {canPost && (q.status === "sent" || q.status === "accepted") && <button aria-label={`Convert ${q.number} to invoice`} title="Convert to invoice" className="p-1" onClick={() => convert.mutate(q.id)}><FileText size={15} /></button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )
      )}

      {tab === "recurring" && (
        <div className="space-y-4">
          {canPost && (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" icon={<Repeat size={14} />} onClick={() => setDialog("recurring")}>New schedule</Button>
              <Button variant="outline" size="sm" disabled={runRec.isPending} onClick={() => runRec.mutate()}>Create due invoices now</Button>
            </div>
          )}
          {recurring.isLoading ? <Skeleton className="h-32" /> : (recurring.data?.length ?? 0) === 0 ? (
            <EmptyState icon={Repeat} title="No recurring invoices" description={canPost ? "Set up a schedule for fees that repeat, such as monthly installments." : "Nothing here yet."} />
          ) : (
            <Card className="overflow-x-auto p-0">
              <table className="w-full">
                <thead><tr><th className={th}>Title</th><th className={th}>Customer</th><th className={th}>Repeats</th><th className={th}>Next invoice</th><th className={th}>Status</th><th className={th}>Created</th><th className={th} /></tr></thead>
                <tbody>
                  {recurring.data!.map((r) => (
                    <tr key={r.id} className="border-t border-[hsl(var(--border))]">
                      <td className={cn(td, "font-medium")}>{r.title}{r.auto_send ? " · auto-send" : ""}{r.last_error && <div className="text-xs text-red-600">{r.last_error}</div>}</td>
                      <td className={td}>{r.customer_name}</td><td className={td}>{FREQ_LABEL[r.frequency]}</td>
                      <td className={td}>{r.status === "ended" ? "—" : r.next_run_date}</td>
                      <td className={cn(td, "capitalize")}>{r.status}</td><td className={td}>{r.run_count}</td>
                      <td className={cn(td, "whitespace-nowrap text-right")}>
                        {canPost && r.status === "active" && <button aria-label={`Pause ${r.title}`} title="Pause" className="p-1" onClick={() => recAct.mutate({ id: r.id, action: "pause" })}><Pause size={15} /></button>}
                        {canPost && r.status === "paused" && <button aria-label={`Resume ${r.title}`} title="Resume" className="p-1" onClick={() => recAct.mutate({ id: r.id, action: "resume" })}><Play size={15} /></button>}
                        {canPost && <button aria-label={`Delete ${r.title}`} title="Delete schedule" className="p-1" onClick={() => delRec.mutate(r.id)}><Trash2 size={15} /></button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      )}

      {tab === "payments" && (
        payments.isLoading ? <Skeleton className="h-32" /> : (payments.data?.items.length ?? 0) === 0 ? (
          <EmptyState icon={Wallet} title="No payments yet" description="Payments you record appear here." />
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full">
              <thead><tr><th className={th}>Number</th><th className={th}>Date</th><th className={th}>Customer</th><th className={th}>Applied to</th><th className={cn(th, "text-right")}>Amount</th><th className={th} /></tr></thead>
              <tbody>
                {payments.data!.items.map((p) => (
                  <tr key={p.id} className={cn("border-t border-[hsl(var(--border))]", p.status === "void" && "text-[hsl(var(--foreground-muted))] line-through")}>
                    <td className={cn(td, "font-medium")}>{p.number}</td><td className={td}>{p.payment_date}</td><td className={td}>{p.customer_name}</td>
                    <td className={td}>{p.allocations.map((a) => a.invoice_number).join(", ") || "Customer credit"}</td>
                    <td className={cn(td, "text-right")}>{formatMoney(p.amount, p.currency)}</td>
                    <td className={cn(td, "text-right")}>
                      {canVoid && p.status === "posted" && <button aria-label={`Void ${p.number}`} title="Void" className="p-1" onClick={() => voidPay.mutate(p.id)}><Ban size={15} /></button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )
      )}

      {tab === "customers" && (
        customers.isLoading ? <Skeleton className="h-32" /> : (customers.data?.length ?? 0) === 0 ? (
          <EmptyState icon={Users} title="No customers yet" description={canPost ? "Add a customer to start invoicing." : "Nothing here yet."} />
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full">
              <thead><tr><th className={th}>Name</th><th className={th}>Email</th><th className={th}>Terms</th><th className={th}>Currency</th><th className={cn(th, "text-right")}>Owes you</th></tr></thead>
              <tbody>
                {customers.data!.map((c) => (
                  <tr key={c.id} className="border-t border-[hsl(var(--border))]">
                    <td className={cn(td, "font-medium")}>{c.name}{c.company ? ` · ${c.company}` : ""}</td><td className={td}>{c.email ?? "—"}</td>
                    <td className={td}>{c.payment_terms_days} days</td><td className={td}>{c.currency ?? base}</td>
                    <td className={cn(td, "text-right font-semibold")}>{formatMoney(c.balance ?? "0", base)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )
      )}

      {dialog === "invoice" && <InvoiceDialog baseCurrency={base} onClose={() => setDialog(null)} />}
      {dialog === "payment" && <PaymentDialog baseCurrency={base} preset={payFor} onClose={() => { setDialog(null); setPayFor(undefined); }} />}
      {dialog === "recurring" && <RecurringDialog baseCurrency={base} onClose={() => setDialog(null)} />}
      {dialog === "quote" && <QuoteDialog baseCurrency={base} onClose={() => setDialog(null)} />}
      {dialog === "customer" && <CustomerDialog onClose={() => setDialog(null)} />}
    </div>
  );
}

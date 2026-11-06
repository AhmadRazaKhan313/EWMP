"use client";

import { useState } from "react";
import { Ban, Check, FileText, PackageCheck, Paperclip, Pause, Play, Plus, Repeat, Send, ShieldCheck, ShoppingCart, Trash2, Users, Wallet, X } from "lucide-react";
import { Button, Card, EmptyState, PageHeader, Skeleton, Tabs } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { formatMoney, useFinSummary } from "@/services/finance.service";
import {
  BILL_LABEL, ORDER_LABEL, needsApproval, useApprovalLimit, useApproveBill, useBillPayments, useBills, useConvertOrder, useDeleteBill,
  useDeleteOrder, useDeleteRecurringBill, useOrderAction, usePostBill, usePurchaseOrders, useRecurringBillAction, useRecurringBills,
  useRequestApproval, useRunRecurringBills, useSetApprovalLimit, useVendors, useVoidBill, useVoidBillPayment,
  type Bill, type BillFilter,
} from "@/services/finance-purchases.service";
import { FREQ_LABEL } from "@/services/finance-sales.service";
import { cn } from "@/utils/cn";
import { AttachmentsDialog } from "./AttachmentsDialog";
import { BillDialog } from "./BillDialog";
import { BillPaymentDialog } from "./BillPaymentDialog";
import { OrderDialog } from "./OrderDialog";
import { RecurringBillDialog } from "./RecurringBillDialog";
import { RejectDialog } from "./RejectDialog";
import { VendorDialog } from "./VendorDialog";

type Tab = "bills" | "orders" | "recurring" | "payments" | "vendors";
const FILTERS: { value: BillFilter | "all"; label: string }[] = [
  { value: "all", label: "All" }, { value: "draft", label: "Draft" }, { value: "open", label: "Open" },
  { value: "overdue", label: "Overdue" }, { value: "paid", label: "Paid" }, { value: "void", label: "Void" },
];

function Pill({ bill }: { bill: Bill }) {
  if (bill.status === "draft" && bill.approval_status === "pending") return <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">Awaiting approval</span>;
  if (bill.status === "draft" && bill.approval_status === "rejected") return <span title={bill.rejection_reason ?? ""} className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">Rejected</span>;
  const key = bill.is_overdue ? "overdue" : bill.status;
  const tone = key === "paid" ? "bg-green-100 text-green-800" : key === "overdue" ? "bg-red-100 text-red-800"
    : key === "void" ? "bg-gray-100 text-gray-500 line-through" : key === "draft" ? "bg-gray-100 text-gray-700" : "bg-blue-100 text-blue-800";
  return <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", tone)}>{BILL_LABEL[key]}</span>;
}

const th = "px-3 py-2 text-left text-xs font-semibold text-[hsl(var(--foreground-muted))]";
const td = "px-3 py-2 text-sm";

export default function PurchasesPage() {
  const { hasPermission } = useAuthStore();
  const canPost = hasPermission("finance.post");
  const canVoid = hasPermission("finance.void");
  const canManage = hasPermission("finance.manage");
  const [tab, setTab] = useState<Tab>("bills");
  const [filter, setFilter] = useState<BillFilter | "all">("all");
  const [dialog, setDialog] = useState<"bill" | "payment" | "vendor" | "order" | "recurring" | null>(null);
  const [filesFor, setFilesFor] = useState<Bill | undefined>();
  const [rejecting, setRejecting] = useState<Bill | undefined>();
  const [limitText, setLimitText] = useState<string | undefined>();
  const [payFor, setPayFor] = useState<Bill | undefined>();

  const base = useFinSummary().data?.currency ?? "PKR";
  const bills = useBills(filter === "all" ? undefined : filter);
  const payments = useBillPayments();
  const vendors = useVendors();
  const post = usePostBill();
  const voidBill = useVoidBill();
  const del = useDeleteBill();
  const voidPay = useVoidBillPayment();
  const limit = useApprovalLimit().data;
  const setLimit = useSetApprovalLimit();
  const reqApproval = useRequestApproval();
  const approve = useApproveBill();
  const orders = usePurchaseOrders();
  const orderAct = useOrderAction();
  const convert = useConvertOrder();
  const delOrder = useDeleteOrder();
  const recurring = useRecurringBills();
  const recAct = useRecurringBillAction();
  const delRec = useDeleteRecurringBill();
  const runRec = useRunRecurringBills();
  const owed = (vendors.data ?? []).reduce((s, v) => s + parseFloat(v.balance ?? "0"), 0);

  return (
    <div className="space-y-6">
      <PageHeader title="Purchases"
        action={
          canPost && (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" icon={<Users size={15} />} onClick={() => setDialog("vendor")}>Add vendor</Button>
              <Button variant="outline" icon={<Wallet size={15} />} onClick={() => { setPayFor(undefined); setDialog("payment"); }}>Pay vendor</Button>
              <Button variant="outline" icon={<ShoppingCart size={15} />} onClick={() => setDialog("order")}>New order</Button>
              <Button icon={<Plus size={15} />} onClick={() => setDialog("bill")}>New bill</Button>
            </div>
          )
        } />

      <Card>
        <p className="text-sm text-[hsl(var(--foreground-muted))]">Payables outstanding</p>
        <p className="mt-1 text-2xl font-semibold" data-testid="stat-payable">{formatMoney(owed, base)}</p>
      </Card>

      {canManage && (
        <Card>
          <label htmlFor="approval-limit" className="text-sm font-medium">Approval limit</label>
          <p className="text-xs text-[hsl(var(--foreground-muted))]">Bills at or above this amount (in {base}) must be approved by someone else before they post. Leave empty to switch approvals off.</p>
          <div className="mt-2 flex gap-2">
            <input id="approval-limit" inputMode="decimal" className="w-40 rounded-md border border-[hsl(var(--border))] bg-transparent px-3 py-2 text-sm"
              value={limitText ?? (limit == null ? "" : String(limit))} onChange={(e) => setLimitText(e.target.value)} />
            <Button size="sm" disabled={setLimit.isPending || limitText === undefined || !(limitText === "" || /^\d+(\.\d{1,2})?$/.test(limitText) && parseFloat(limitText) > 0)}
              onClick={() => setLimit.mutate(limitText === "" ? null : limitText!, { onSuccess: () => setLimitText(undefined) })}>Save limit</Button>
          </div>
        </Card>
      )}

      <Tabs<Tab> active={tab} onChange={setTab}
        tabs={[{ value: "bills", label: "Bills" }, { value: "orders", label: "Orders" }, { value: "recurring", label: "Recurring" }, { value: "payments", label: "Payments" }, { value: "vendors", label: "Vendors" }]} />

      {tab === "bills" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {FILTERS.map((f) => (
              <button key={f.value} onClick={() => setFilter(f.value)} aria-pressed={filter === f.value}
                className={cn("rounded-full border px-3 py-1 text-sm", filter === f.value ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]" : "border-[hsl(var(--border))]")}>
                {f.label}
              </button>
            ))}
          </div>
          {bills.isLoading ? <Skeleton className="h-32" /> : (bills.data?.items.length ?? 0) === 0 ? (
            <EmptyState icon={FileText} title="No bills" description={canPost ? "Enter the first bill from a vendor." : "Nothing here yet."} />
          ) : (
            <Card className="overflow-x-auto p-0">
              <table className="w-full">
                <thead><tr><th className={th}>Number</th><th className={th}>Vendor</th><th className={th}>Date</th><th className={th}>Due</th><th className={th}>Status</th><th className={cn(th, "text-right")}>Total</th><th className={cn(th, "text-right")}>Balance</th><th className={th} /></tr></thead>
                <tbody>
                  {bills.data!.items.map((b) => (
                    <tr key={b.id} className="border-t border-[hsl(var(--border))]">
                      <td className={cn(td, "font-medium")}>{b.number}{b.vendor_ref && <div className="text-xs font-normal text-[hsl(var(--foreground-muted))]">{b.vendor_ref}</div>}</td>
                      <td className={td}>{b.vendor_name}</td><td className={td}>{b.issue_date}</td><td className={td}>{b.due_date}</td>
                      <td className={td}><Pill bill={b} /></td>
                      <td className={cn(td, "text-right")}>{formatMoney(b.total, b.currency)}</td>
                      <td className={cn(td, "text-right font-semibold")}>{formatMoney(b.balance, b.currency)}</td>
                      <td className={cn(td, "whitespace-nowrap text-right")}>
                        <button aria-label={`Files ${b.number}`} title="Files" className="p-1" onClick={() => setFilesFor(b)}><Paperclip size={15} /></button>
                        {canPost && b.status === "draft" && !needsApproval(b, limit) && <button aria-label={`Post ${b.number}`} title="Post" className="p-1" onClick={() => post.mutate(b.id)}><Send size={15} /></button>}
                        {canPost && b.status === "draft" && needsApproval(b, limit) && b.approval_status !== "pending" && (
                          <button aria-label={`Request approval ${b.number}`} title="Request approval" className="p-1" onClick={() => reqApproval.mutate(b.id)}><ShieldCheck size={15} /></button>
                        )}
                        {canManage && b.status === "draft" && b.approval_status === "pending" && (
                          <>
                            <button aria-label={`Approve ${b.number}`} title="Approve and post" className="p-1" onClick={() => approve.mutate(b.id)}><Check size={15} /></button>
                            <button aria-label={`Reject ${b.number}`} title="Reject" className="p-1" onClick={() => setRejecting(b)}><X size={15} /></button>
                          </>
                        )}
                        {canPost && b.status === "draft" && <button aria-label={`Delete ${b.number}`} title="Delete draft" className="p-1" onClick={() => del.mutate(b.id)}><Trash2 size={15} /></button>}
                        {canPost && (b.status === "open" || b.status === "partially_paid") && (
                          <button aria-label={`Pay ${b.number}`} title="Pay" className="p-1" onClick={() => { setPayFor(b); setDialog("payment"); }}><Wallet size={15} /></button>
                        )}
                        {canVoid && b.status === "open" && <button aria-label={`Void ${b.number}`} title="Void" className="p-1" onClick={() => voidBill.mutate(b.id)}><Ban size={15} /></button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      )}

      {tab === "orders" && (
        orders.isLoading ? <Skeleton className="h-32" /> : (orders.data?.length ?? 0) === 0 ? (
          <EmptyState icon={ShoppingCart} title="No purchase orders" description={canPost ? "Raise an order before you buy; turn it into a bill when the invoice arrives." : "Nothing here yet."} />
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full">
              <thead><tr><th className={th}>Number</th><th className={th}>Vendor</th><th className={th}>Ordered</th><th className={th}>Expected</th><th className={th}>Status</th><th className={cn(th, "text-right")}>Total</th><th className={th} /></tr></thead>
              <tbody>
                {orders.data!.map((o) => (
                  <tr key={o.id} className="border-t border-[hsl(var(--border))]">
                    <td className={cn(td, "font-medium")}>{o.number}</td><td className={td}>{o.vendor_name}</td><td className={td}>{o.issue_date}</td>
                    <td className={td}>{o.expected_date ?? "—"}</td><td className={td}>{ORDER_LABEL[o.status]}</td>
                    <td className={cn(td, "text-right")}>{formatMoney(o.total, o.currency)}</td>
                    <td className={cn(td, "whitespace-nowrap text-right")}>
                      {canPost && o.status === "draft" && <button aria-label={`Send ${o.number}`} title="Mark sent" className="p-1" onClick={() => orderAct.mutate({ id: o.id, action: "sent" })}><Send size={15} /></button>}
                      {canPost && o.status === "sent" && <button aria-label={`Receive ${o.number}`} title="Mark received" className="p-1" onClick={() => orderAct.mutate({ id: o.id, action: "received" })}><PackageCheck size={15} /></button>}
                      {canPost && (o.status === "sent" || o.status === "received") && <button aria-label={`Bill ${o.number}`} title="Create bill" className="p-1" onClick={() => convert.mutate(o.id)}><FileText size={15} /></button>}
                      {canPost && (o.status === "draft" || o.status === "sent") && <button aria-label={`Cancel ${o.number}`} title="Cancel order" className="p-1" onClick={() => orderAct.mutate({ id: o.id, action: "cancelled" })}><Ban size={15} /></button>}
                      {canPost && o.status === "draft" && <button aria-label={`Delete ${o.number}`} title="Delete draft" className="p-1" onClick={() => delOrder.mutate(o.id)}><Trash2 size={15} /></button>}
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
              <Button variant="outline" size="sm" disabled={runRec.isPending} onClick={() => runRec.mutate()}>Create due bills now</Button>
            </div>
          )}
          {recurring.isLoading ? <Skeleton className="h-32" /> : (recurring.data?.length ?? 0) === 0 ? (
            <EmptyState icon={Repeat} title="No recurring bills" description={canPost ? "Set up a schedule for bills that repeat, such as rent or internet." : "Nothing here yet."} />
          ) : (
            <Card className="overflow-x-auto p-0">
              <table className="w-full">
                <thead><tr><th className={th}>Title</th><th className={th}>Vendor</th><th className={th}>Repeats</th><th className={th}>Next bill</th><th className={th}>Status</th><th className={th}>Created</th><th className={th} /></tr></thead>
                <tbody>
                  {recurring.data!.map((r) => (
                    <tr key={r.id} className="border-t border-[hsl(var(--border))]">
                      <td className={cn(td, "font-medium")}>{r.title}{r.auto_post ? " · auto-post" : ""}{r.last_error && <div className="text-xs text-red-600">{r.last_error}</div>}</td>
                      <td className={td}>{r.vendor_name}</td><td className={td}>{FREQ_LABEL[r.frequency]}</td>
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
          <EmptyState icon={Wallet} title="No payments yet" description="Payments you make to vendors appear here." />
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full">
              <thead><tr><th className={th}>Number</th><th className={th}>Date</th><th className={th}>Vendor</th><th className={th}>Applied to</th><th className={cn(th, "text-right")}>Amount</th><th className={th} /></tr></thead>
              <tbody>
                {payments.data!.items.map((p) => (
                  <tr key={p.id} className={cn("border-t border-[hsl(var(--border))]", p.status === "void" && "text-[hsl(var(--foreground-muted))] line-through")}>
                    <td className={cn(td, "font-medium")}>{p.number}</td><td className={td}>{p.payment_date}</td><td className={td}>{p.vendor_name}</td>
                    <td className={td}>{p.allocations.map((a) => a.bill_number).join(", ") || "Advance"}</td>
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

      {tab === "vendors" && (
        vendors.isLoading ? <Skeleton className="h-32" /> : (vendors.data?.length ?? 0) === 0 ? (
          <EmptyState icon={Users} title="No vendors yet" description={canPost ? "Add a vendor to start entering bills." : "Nothing here yet."} />
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full">
              <thead><tr><th className={th}>Name</th><th className={th}>Email</th><th className={th}>Terms</th><th className={th}>Currency</th><th className={cn(th, "text-right")}>You owe</th></tr></thead>
              <tbody>
                {vendors.data!.map((v) => (
                  <tr key={v.id} className="border-t border-[hsl(var(--border))]">
                    <td className={cn(td, "font-medium")}>{v.name}{v.company ? ` · ${v.company}` : ""}</td><td className={td}>{v.email ?? "—"}</td>
                    <td className={td}>{v.payment_terms_days} days</td><td className={td}>{v.currency ?? base}</td>
                    <td className={cn(td, "text-right font-semibold")}>{formatMoney(v.balance ?? "0", base)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )
      )}

      {dialog === "bill" && <BillDialog baseCurrency={base} onClose={() => setDialog(null)} />}
      {dialog === "payment" && <BillPaymentDialog baseCurrency={base} preset={payFor} onClose={() => { setDialog(null); setPayFor(undefined); }} />}
      {dialog === "vendor" && <VendorDialog onClose={() => setDialog(null)} />}
      {dialog === "order" && <OrderDialog baseCurrency={base} onClose={() => setDialog(null)} />}
      {dialog === "recurring" && <RecurringBillDialog baseCurrency={base} onClose={() => setDialog(null)} />}
      {filesFor && <AttachmentsDialog bill={filesFor} canEdit={canPost} onClose={() => setFilesFor(undefined)} />}
      {rejecting && <RejectDialog bill={rejecting} onClose={() => setRejecting(undefined)} />}
    </div>
  );
}

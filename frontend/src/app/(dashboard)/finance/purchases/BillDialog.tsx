"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/atoms";
import { formatMoney, useFinAccounts } from "@/services/finance.service";
import { billAccounts, needsApproval, useApprovalLimit, useCreateBill, useVendors, type BillLine } from "@/services/finance-purchases.service";
import { lineNet, useTaxRates } from "@/services/finance-sales.service";
import { inp, Modal } from "../sales/CustomerDialog";
import { VendorDialog } from "./VendorDialog";

const today = () => new Date().toISOString().slice(0, 10);
const blank = (): BillLine => ({ description: "", quantity: "1", unit_price: "", discount_percent: "0", tax_rate_id: null, expense_account_id: null });
const num = /^\d+(\.\d+)?$/;

export function BillDialog({ baseCurrency, onClose }: { baseCurrency: string; onClose: () => void }) {
  const vendors = useVendors();
  const taxes = useTaxRates();
  const accounts = useFinAccounts();
  const create = useCreateBill();
  const limit = useApprovalLimit().data;
  const [vendorId, setVendorId] = useState("");
  const [issue, setIssue] = useState(today());
  const [due, setDue] = useState("");
  const [currency, setCurrency] = useState("");
  const [rate, setRate] = useState("");
  const [ref, setRef] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<BillLine[]>([blank()]);
  const [addingVendor, setAddingVendor] = useState(false);

  const vendor = vendors.data?.find((v) => v.id === vendorId);
  const cur = (currency || vendor?.currency || baseCurrency).toUpperCase();
  const foreign = cur !== baseCurrency.toUpperCase();
  const expenseAccounts = billAccounts(accounts.data ?? []);
  const pct = (id: string | null) => parseFloat(taxes.data?.find((t) => t.id === id)?.percent ?? "0");
  const subtotal = lines.reduce((s, l) => s + lineNet(l), 0);
  const tax = lines.reduce((s, l) => s + Math.round(lineNet(l) * pct(l.tax_rate_id)) / 100, 0);
  const linesOk = lines.every((l) => l.description.trim() && num.test(l.quantity) && parseFloat(l.quantity) > 0 && num.test(l.unit_price));
  const ready = !!vendorId && !!issue && linesOk && (!due || due >= issue) && (!rate || (num.test(rate) && parseFloat(rate) > 0));
  const rateNum = foreign ? parseFloat(rate || "0") || 0 : 1;
  const overLimit = needsApproval({ total: String(subtotal + tax), exchange_rate: String(rateNum || 1) }, limit) && (!foreign || rateNum > 0);
  const patch = (i: number, p: Partial<BillLine>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...p } : l)));

  async function save(post: boolean) {
    await create.mutateAsync({
      vendor_id: vendorId, issue_date: issue, due_date: due || undefined, currency: currency ? cur : undefined,
      rate: foreign && rate ? rate : undefined, vendor_ref: ref.trim() || undefined, notes: notes.trim() || undefined, post,
      lines: lines.map((l) => ({
        description: l.description.trim(), quantity: l.quantity, unit_price: l.unit_price,
        discount_percent: l.discount_percent || "0", tax_rate_id: l.tax_rate_id || undefined,
        expense_account_id: l.expense_account_id || undefined,
      })),
    });
    onClose();
  }

  return (
    <>
      <Modal title="New bill" onClose={onClose} footer={
        <>
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="outline" size="sm" disabled={!ready || create.isPending} onClick={() => void save(false)}>Save as draft</Button>
          <span title={overLimit ? "Above the approval limit: save as draft, then request approval" : undefined}>
            <Button size="sm" disabled={!ready || create.isPending || overLimit} onClick={() => void save(true)}>{create.isPending ? "Saving…" : "Save & post"}</Button>
          </span>
        </>
      }>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="b-vendor" className="mb-1 block text-xs font-medium">Vendor</label>
            <select id="b-vendor" className={inp} value={vendorId}
              onChange={(e) => (e.target.value === "__new__" ? setAddingVendor(true) : setVendorId(e.target.value))}>
              <option value="">Select…</option>
              {vendors.data?.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
              <option value="__new__">+ New vendor…</option>
            </select>
          </div>
          <div><label htmlFor="b-ref" className="mb-1 block text-xs font-medium">Vendor's invoice no (optional)</label><input id="b-ref" className={inp} value={ref} onChange={(e) => setRef(e.target.value)} /></div>
          <div><label htmlFor="b-issue" className="mb-1 block text-xs font-medium">Bill date</label><input id="b-issue" type="date" className={inp} value={issue} onChange={(e) => setIssue(e.target.value)} /></div>
          <div><label htmlFor="b-due" className="mb-1 block text-xs font-medium">Due date (blank = vendor terms)</label><input id="b-due" type="date" className={inp} value={due} onChange={(e) => setDue(e.target.value)} /></div>
          <div><label htmlFor="b-cur" className="mb-1 block text-xs font-medium">Currency</label><input id="b-cur" maxLength={3} className={inp} placeholder={vendor?.currency ?? baseCurrency} value={currency} onChange={(e) => setCurrency(e.target.value)} /></div>
          {foreign && (
            <div><label htmlFor="b-rate" className="mb-1 block text-xs font-medium">Exchange rate to {baseCurrency} (blank = saved rate)</label><input id="b-rate" inputMode="decimal" className={inp} value={rate} onChange={(e) => setRate(e.target.value)} /></div>
          )}
        </div>

        <div className="space-y-2">
          {lines.map((l, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[1fr_150px_60px_90px_60px_120px_auto]">
              <input aria-label={`Description ${i + 1}`} placeholder="Description" className={inp} value={l.description} onChange={(e) => patch(i, { description: e.target.value })} />
              <select aria-label={`Expense account ${i + 1}`} className={inp} value={l.expense_account_id ?? ""} onChange={(e) => patch(i, { expense_account_id: e.target.value || null })}>
                <option value="">Other Expenses</option>
                {expenseAccounts.filter((a) => a.code !== "5900").map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
              <input aria-label={`Quantity ${i + 1}`} inputMode="decimal" className={inp} value={l.quantity} onChange={(e) => patch(i, { quantity: e.target.value })} />
              <input aria-label={`Price ${i + 1}`} inputMode="decimal" placeholder="Price" className={inp} value={l.unit_price} onChange={(e) => patch(i, { unit_price: e.target.value })} />
              <input aria-label={`Discount ${i + 1}`} inputMode="decimal" placeholder="Disc %" className={inp} value={l.discount_percent} onChange={(e) => patch(i, { discount_percent: e.target.value })} />
              <select aria-label={`Tax ${i + 1}`} className={inp} value={l.tax_rate_id ?? ""} onChange={(e) => patch(i, { tax_rate_id: e.target.value || null })}>
                <option value="">No tax</option>
                {taxes.data?.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.percent}%)</option>)}
              </select>
              <button aria-label={`Remove line ${i + 1}`} disabled={lines.length === 1} className="justify-self-start p-2 disabled:opacity-30"
                onClick={() => setLines(lines.filter((_, j) => j !== i))}><Trash2 size={16} /></button>
            </div>
          ))}
          <Button variant="outline" size="sm" icon={<Plus size={14} />} onClick={() => setLines([...lines, blank()])}>Add line</Button>
        </div>

        <div className="ml-auto w-full max-w-xs space-y-1 text-sm">
          <div className="flex justify-between"><span>Subtotal</span><span data-testid="bill-subtotal">{formatMoney(subtotal, cur)}</span></div>
          <div className="flex justify-between"><span>Tax</span><span>{formatMoney(tax, cur)}</span></div>
          <div className="flex justify-between border-t border-[hsl(var(--border))] pt-1 font-semibold"><span>Total</span><span data-testid="bill-total">{formatMoney(subtotal + tax, cur)}</span></div>
        </div>
        {overLimit && <p role="status" className="text-xs text-amber-700">This bill is above the approval limit. Save it as a draft, then request approval.</p>}
        <div><label htmlFor="b-notes" className="mb-1 block text-xs font-medium">Notes</label><textarea id="b-notes" rows={2} className={inp} value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
      </Modal>
      {addingVendor && <VendorDialog onClose={() => setAddingVendor(false)} onCreated={setVendorId} />}
    </>
  );
}

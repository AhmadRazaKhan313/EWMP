"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/atoms";
import { formatMoney } from "@/services/finance.service";
import { lineNet, useCreateQuote, useCustomers, useTaxRates, type InvoiceLine } from "@/services/finance-sales.service";
import { CustomerDialog, inp, Modal } from "./CustomerDialog";

const today = () => new Date().toISOString().slice(0, 10);
const blank = (): InvoiceLine => ({ description: "", quantity: "1", unit_price: "", discount_percent: "0", tax_rate_id: null });
const num = /^\d+(\.\d+)?$/;

export function QuoteDialog({ baseCurrency, onClose }: { baseCurrency: string; onClose: () => void }) {
  const customers = useCustomers();
  const taxes = useTaxRates();
  const create = useCreateQuote();
  const [customerId, setCustomerId] = useState("");
  const [issue, setIssue] = useState(today());
  const [due, setDue] = useState("");
  const [currency, setCurrency] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<InvoiceLine[]>([blank()]);
  const [addingCustomer, setAddingCustomer] = useState(false);

  const cust = customers.data?.find((c) => c.id === customerId);
  const cur = (currency || cust?.currency || baseCurrency).toUpperCase();
  const pct = (id: string | null) => parseFloat(taxes.data?.find((t) => t.id === id)?.percent ?? "0");
  const subtotal = lines.reduce((s, l) => s + lineNet(l), 0);
  const tax = lines.reduce((s, l) => s + (Math.round(lineNet(l) * pct(l.tax_rate_id)) / 100), 0);
  const linesOk = lines.every((l) => l.description.trim() && num.test(l.quantity) && parseFloat(l.quantity) > 0 && num.test(l.unit_price));
  const ready = !!customerId && !!issue && linesOk && (!due || due >= issue);

  const patch = (i: number, p: Partial<InvoiceLine>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...p } : l)));

  async function save(send: boolean) {
    await create.mutateAsync({
      customer_id: customerId, issue_date: issue, valid_until: due || undefined, currency: currency ? cur : undefined,
      notes: notes.trim() || undefined, send,
      lines: lines.map((l) => ({
        description: l.description.trim(), quantity: l.quantity, unit_price: l.unit_price,
        discount_percent: l.discount_percent || "0", tax_rate_id: l.tax_rate_id || undefined,
      })),
    });
    onClose();
  }

  return (
    <>
      <Modal title="New quote" onClose={onClose} footer={
        <>
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="outline" size="sm" disabled={!ready || create.isPending} onClick={() => void save(false)}>Save as draft</Button>
          <Button size="sm" disabled={!ready || create.isPending} onClick={() => void save(true)}>{create.isPending ? "Saving…" : "Save & mark sent"}</Button>
        </>
      }>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="i-cust" className="mb-1 block text-xs font-medium">Customer</label>
            <select id="i-cust" className={inp} value={customerId}
              onChange={(e) => (e.target.value === "__new__" ? setAddingCustomer(true) : setCustomerId(e.target.value))}>
              <option value="">Select…</option>
              {customers.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              <option value="__new__">+ New customer…</option>
            </select>
          </div>
          <div>
            <label htmlFor="i-cur" className="mb-1 block text-xs font-medium">Currency</label>
            <input id="i-cur" maxLength={3} className={inp} placeholder={cust?.currency ?? baseCurrency} value={currency} onChange={(e) => setCurrency(e.target.value)} />
          </div>
          <div><label htmlFor="i-issue" className="mb-1 block text-xs font-medium">Issue date</label><input id="i-issue" type="date" className={inp} value={issue} onChange={(e) => setIssue(e.target.value)} /></div>
          <div><label htmlFor="q-due" className="mb-1 block text-xs font-medium">Valid until (blank = 30 days)</label><input id="q-due" type="date" className={inp} value={due} onChange={(e) => setDue(e.target.value)} /></div>
        </div>

        <div className="space-y-2">
          {lines.map((l, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[1fr_70px_100px_70px_130px_auto]">
              <input aria-label={`Description ${i + 1}`} placeholder="Description" className={inp} value={l.description} onChange={(e) => patch(i, { description: e.target.value })} />
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
          <div className="flex justify-between"><span>Subtotal</span><span data-testid="inv-subtotal">{formatMoney(subtotal, cur)}</span></div>
          <div className="flex justify-between"><span>Tax</span><span>{formatMoney(tax, cur)}</span></div>
          <div className="flex justify-between border-t border-[hsl(var(--border))] pt-1 font-semibold"><span>Total</span><span data-testid="inv-total">{formatMoney(subtotal + tax, cur)}</span></div>
        </div>
        <div><label htmlFor="i-notes" className="mb-1 block text-xs font-medium">Notes</label><textarea id="i-notes" rows={2} className={inp} value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
      </Modal>
      {addingCustomer && <CustomerDialog onClose={() => setAddingCustomer(false)} onCreated={setCustomerId} />}
    </>
  );
}

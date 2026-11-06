"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/atoms";
import { formatMoney } from "@/services/finance.service";
import {
  FREQ_LABEL, lineNet, useCreateRecurring, useCustomers, useTaxRates, type Frequency, type InvoiceLine,
} from "@/services/finance-sales.service";
import { inp, Modal } from "./CustomerDialog";

const today = () => new Date().toISOString().slice(0, 10);
const blank = (): InvoiceLine => ({ description: "", quantity: "1", unit_price: "", discount_percent: "0", tax_rate_id: null });
const num = /^\d+(\.\d+)?$/;

export function RecurringDialog({ baseCurrency, onClose }: { baseCurrency: string; onClose: () => void }) {
  const customers = useCustomers();
  const taxes = useTaxRates();
  const create = useCreateRecurring();
  const [title, setTitle] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [frequency, setFrequency] = useState<Frequency>("monthly");
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState("");
  const [autoSend, setAutoSend] = useState(false);
  const [lines, setLines] = useState<InvoiceLine[]>([blank()]);

  const cust = customers.data?.find((c) => c.id === customerId);
  const cur = (cust?.currency ?? baseCurrency).toUpperCase();
  const pct = (id: string | null) => parseFloat(taxes.data?.find((t) => t.id === id)?.percent ?? "0");
  const subtotal = lines.reduce((s, l) => s + lineNet(l), 0);
  const total = subtotal + lines.reduce((s, l) => s + Math.round(lineNet(l) * pct(l.tax_rate_id)) / 100, 0);
  const linesOk = lines.every((l) => l.description.trim() && num.test(l.quantity) && parseFloat(l.quantity) > 0 && num.test(l.unit_price));
  const ready = title.trim().length > 0 && !!customerId && !!start && linesOk && (!end || end >= start);
  const patch = (i: number, p: Partial<InvoiceLine>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...p } : l)));

  async function save() {
    await create.mutateAsync({
      title: title.trim(), customer_id: customerId, frequency, start_date: start, end_date: end || undefined, auto_send: autoSend,
      lines: lines.map((l) => ({
        description: l.description.trim(), quantity: l.quantity, unit_price: l.unit_price,
        discount_percent: l.discount_percent || "0", tax_rate_id: l.tax_rate_id || undefined,
      })),
    });
    onClose();
  }

  return (
    <Modal title="New recurring invoice" onClose={onClose} footer={
      <>
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" disabled={!ready || create.isPending} onClick={() => void save()}>{create.isPending ? "Saving…" : "Save schedule"}</Button>
      </>
    }>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><label htmlFor="r-title" className="mb-1 block text-xs font-medium">Title</label><input id="r-title" className={inp} placeholder="e.g. Monthly web retainer" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
        <div>
          <label htmlFor="r-cust" className="mb-1 block text-xs font-medium">Customer</label>
          <select id="r-cust" className={inp} value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
            <option value="">Select…</option>
            {customers.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="r-freq" className="mb-1 block text-xs font-medium">Repeats</label>
          <select id="r-freq" className={inp} value={frequency} onChange={(e) => setFrequency(e.target.value as Frequency)}>
            {(Object.keys(FREQ_LABEL) as Frequency[]).map((f) => <option key={f} value={f}>{FREQ_LABEL[f]}</option>)}
          </select>
        </div>
        <div><label htmlFor="r-start" className="mb-1 block text-xs font-medium">First invoice on</label><input id="r-start" type="date" className={inp} value={start} onChange={(e) => setStart(e.target.value)} /></div>
        <div><label htmlFor="r-end" className="mb-1 block text-xs font-medium">Stop after (optional)</label><input id="r-end" type="date" className={inp} value={end} onChange={(e) => setEnd(e.target.value)} /></div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={autoSend} onChange={(e) => setAutoSend(e.target.checked)} />
        Send automatically (post to the books). Otherwise each invoice is created as a draft for you to review.
      </label>

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
      <p className="text-right text-sm font-semibold" data-testid="rec-total">Each invoice: {formatMoney(total, cur)}</p>
    </Modal>
  );
}

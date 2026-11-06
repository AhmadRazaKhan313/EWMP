"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/atoms";
import { formatMoney, isMoneyAccount, useFinAccounts } from "@/services/finance.service";
import { fetchOpenInvoices, useCreatePayment, useCustomers, type Invoice } from "@/services/finance-sales.service";
import { inp, Modal } from "./CustomerDialog";

const today = () => new Date().toISOString().slice(0, 10);
const num = /^\d+(\.\d{1,2})?$/;

export function PaymentDialog({ baseCurrency, preset, onClose }: { baseCurrency: string; preset?: Invoice; onClose: () => void }) {
  const customers = useCustomers();
  const accounts = useFinAccounts();
  const create = useCreatePayment();
  const money = useMemo(() => (accounts.data ?? []).filter(isMoneyAccount), [accounts.data]);
  const [customerId, setCustomerId] = useState(preset?.customer_id ?? "");
  const [date, setDate] = useState(today());
  const [amount, setAmount] = useState(preset?.balance ?? "");
  const [depositId, setDepositId] = useState("");
  const [rate, setRate] = useState("");
  const [open, setOpen] = useState<Invoice[]>([]);
  const [alloc, setAlloc] = useState<Record<string, string>>(preset ? { [preset.id]: preset.balance } : {});

  useEffect(() => {
    if (!customerId) { setOpen([]); return; }
    let live = true;
    void fetchOpenInvoices(customerId).then((r) => { if (live) setOpen(r); });
    return () => { live = false; };
  }, [customerId]);
  useEffect(() => { if (!depositId && money[0]) setDepositId(money[0].id); }, [money, depositId]);

  const cust = customers.data?.find((c) => c.id === customerId);
  const cur = (preset?.currency ?? open[0]?.currency ?? cust?.currency ?? baseCurrency).toUpperCase();
  const foreign = cur !== baseCurrency.toUpperCase();
  const applied = Object.values(alloc).reduce((s, v) => s + (num.test(v) ? parseFloat(v) : 0), 0);
  const total = num.test(amount) ? parseFloat(amount) : 0;
  const over = open.some((i) => num.test(alloc[i.id] ?? "") && parseFloat(alloc[i.id] ?? "0") > parseFloat(i.balance));
  const ready = !!customerId && !!depositId && total > 0 && applied <= total + 1e-9 && !over && (!foreign || !rate || parseFloat(rate) > 0);

  async function save() {
    await create.mutateAsync({
      customer_id: customerId, payment_date: date, amount, deposit_account_id: depositId,
      currency: foreign ? cur : undefined, rate: foreign && rate ? rate : undefined,
      allocations: Object.entries(alloc).filter(([, v]) => num.test(v) && parseFloat(v) > 0).map(([invoice_id, a]) => ({ invoice_id, amount: a })),
    });
    onClose();
  }

  return (
    <Modal title="Record payment" onClose={onClose} footer={
      <>
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" disabled={!ready || create.isPending} onClick={() => void save()}>{create.isPending ? "Saving…" : "Save payment"}</Button>
      </>
    }>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="p-cust" className="mb-1 block text-xs font-medium">Customer</label>
          <select id="p-cust" className={inp} value={customerId} disabled={!!preset} onChange={(e) => { setCustomerId(e.target.value); setAlloc({}); }}>
            <option value="">Select…</option>
            {customers.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="p-dep" className="mb-1 block text-xs font-medium">Deposit to</label>
          <select id="p-dep" className={inp} value={depositId} onChange={(e) => setDepositId(e.target.value)}>
            {money.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div><label htmlFor="p-amt" className="mb-1 block text-xs font-medium">Amount received ({cur})</label><input id="p-amt" inputMode="decimal" className={inp} value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
        <div><label htmlFor="p-date" className="mb-1 block text-xs font-medium">Date</label><input id="p-date" type="date" className={inp} value={date} onChange={(e) => setDate(e.target.value)} /></div>
        {foreign && (
          <div className="sm:col-span-2">
            <label htmlFor="p-rate" className="mb-1 block text-xs font-medium">Exchange rate on this day (blank = saved rate)</label>
            <input id="p-rate" inputMode="decimal" className={inp} value={rate} onChange={(e) => setRate(e.target.value)} />
          </div>
        )}
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold">Apply to invoices</h3>
        {customerId && open.length === 0 && <p className="text-sm text-[hsl(var(--foreground-muted))]">No open invoices. The whole amount will be kept as customer credit.</p>}
        {open.map((i) => (
          <div key={i.id} className="flex items-center justify-between gap-3 text-sm">
            <span>{i.number} · due {i.due_date} · balance {formatMoney(i.balance, i.currency)}</span>
            <input aria-label={`Apply to ${i.number}`} inputMode="decimal" className={`${inp} w-32`} value={alloc[i.id] ?? ""}
              onChange={(e) => setAlloc({ ...alloc, [i.id]: e.target.value })} />
          </div>
        ))}
        <p className="text-xs text-[hsl(var(--foreground-muted))]" data-testid="pay-unapplied">
          Applied {formatMoney(applied, cur)} · kept as credit {formatMoney(Math.max(0, total - applied), cur)}
          {applied > total + 1e-9 && " — allocations exceed the payment"}{over && " — more than an invoice balance"}
        </p>
      </div>
    </Modal>
  );
}

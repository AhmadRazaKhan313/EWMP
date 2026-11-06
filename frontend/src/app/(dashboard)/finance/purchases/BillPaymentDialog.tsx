"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/atoms";
import { formatMoney, isMoneyAccount, useFinAccounts } from "@/services/finance.service";
import { fetchOpenBills, useCreateBillPayment, useVendors, type Bill } from "@/services/finance-purchases.service";
import { inp, Modal } from "../sales/CustomerDialog";

const today = () => new Date().toISOString().slice(0, 10);
const num = /^\d+(\.\d{1,2})?$/;

export function BillPaymentDialog({ baseCurrency, preset, onClose }: { baseCurrency: string; preset?: Bill; onClose: () => void }) {
  const vendors = useVendors();
  const accounts = useFinAccounts();
  const create = useCreateBillPayment();
  const money = useMemo(() => (accounts.data ?? []).filter(isMoneyAccount), [accounts.data]);
  const [vendorId, setVendorId] = useState(preset?.vendor_id ?? "");
  const [date, setDate] = useState(today());
  const [amount, setAmount] = useState(preset?.balance ?? "");
  const [fromId, setFromId] = useState("");
  const [rate, setRate] = useState("");
  const [open, setOpen] = useState<Bill[]>([]);
  const [alloc, setAlloc] = useState<Record<string, string>>(preset ? { [preset.id]: preset.balance } : {});

  useEffect(() => {
    if (!vendorId) { setOpen([]); return; }
    let live = true;
    void fetchOpenBills(vendorId).then((r) => { if (live) setOpen(r); });
    return () => { live = false; };
  }, [vendorId]);
  useEffect(() => { if (!fromId && money[0]) setFromId(money[0].id); }, [money, fromId]);

  const vendor = vendors.data?.find((v) => v.id === vendorId);
  const cur = (preset?.currency ?? open[0]?.currency ?? vendor?.currency ?? baseCurrency).toUpperCase();
  const foreign = cur !== baseCurrency.toUpperCase();
  const applied = Object.values(alloc).reduce((s, v) => s + (num.test(v) ? parseFloat(v) : 0), 0);
  const total = num.test(amount) ? parseFloat(amount) : 0;
  const over = open.some((b) => num.test(alloc[b.id] ?? "") && parseFloat(alloc[b.id] ?? "0") > parseFloat(b.balance));
  const ready = !!vendorId && !!fromId && total > 0 && applied <= total + 1e-9 && !over && (!foreign || !rate || parseFloat(rate) > 0);

  async function save() {
    await create.mutateAsync({
      vendor_id: vendorId, payment_date: date, amount, paid_from_account_id: fromId,
      currency: foreign ? cur : undefined, rate: foreign && rate ? rate : undefined,
      allocations: Object.entries(alloc).filter(([, v]) => num.test(v) && parseFloat(v) > 0).map(([bill_id, a]) => ({ bill_id, amount: a })),
    });
    onClose();
  }

  return (
    <Modal title="Pay vendor" onClose={onClose} footer={
      <>
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" disabled={!ready || create.isPending} onClick={() => void save()}>{create.isPending ? "Saving…" : "Save payment"}</Button>
      </>
    }>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="bp-vendor" className="mb-1 block text-xs font-medium">Vendor</label>
          <select id="bp-vendor" className={inp} value={vendorId} disabled={!!preset} onChange={(e) => { setVendorId(e.target.value); setAlloc({}); }}>
            <option value="">Select…</option>
            {vendors.data?.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="bp-from" className="mb-1 block text-xs font-medium">Paid from</label>
          <select id="bp-from" className={inp} value={fromId} onChange={(e) => setFromId(e.target.value)}>
            {money.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div><label htmlFor="bp-amt" className="mb-1 block text-xs font-medium">Amount paid ({cur})</label><input id="bp-amt" inputMode="decimal" className={inp} value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
        <div><label htmlFor="bp-date" className="mb-1 block text-xs font-medium">Date</label><input id="bp-date" type="date" className={inp} value={date} onChange={(e) => setDate(e.target.value)} /></div>
        {foreign && (
          <div className="sm:col-span-2"><label htmlFor="bp-rate" className="mb-1 block text-xs font-medium">Exchange rate on this day (blank = saved rate)</label><input id="bp-rate" inputMode="decimal" className={inp} value={rate} onChange={(e) => setRate(e.target.value)} /></div>
        )}
      </div>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">Apply to bills</h3>
        {vendorId && open.length === 0 && <p className="text-sm text-[hsl(var(--foreground-muted))]">No open bills. The whole amount will be kept as an advance to the vendor.</p>}
        {open.map((b) => (
          <div key={b.id} className="flex items-center justify-between gap-3 text-sm">
            <span>{b.number} · due {b.due_date} · balance {formatMoney(b.balance, b.currency)}</span>
            <input aria-label={`Apply to ${b.number}`} inputMode="decimal" className={`${inp} w-32`} value={alloc[b.id] ?? ""} onChange={(e) => setAlloc({ ...alloc, [b.id]: e.target.value })} />
          </div>
        ))}
        <p className="text-xs text-[hsl(var(--foreground-muted))]" data-testid="bpay-unapplied">
          Applied {formatMoney(applied, cur)} · kept as advance {formatMoney(Math.max(0, total - applied), cur)}
          {applied > total + 1e-9 && " — allocations exceed the payment"}{over && " — more than a bill balance"}
        </p>
      </div>
    </Modal>
  );
}

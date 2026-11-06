"use client";

import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/atoms";
import { formatMoney, useFinAccounts } from "@/services/finance.service";
import { billAccounts, type BillLine } from "@/services/finance-purchases.service";
import { lineNet, useTaxRates } from "@/services/finance-sales.service";
import { inp } from "../sales/CustomerDialog";

export const blankLine = (): BillLine => ({ description: "", quantity: "1", unit_price: "", discount_percent: "0", tax_rate_id: null, expense_account_id: null });
const num = /^\d+(\.\d+)?$/;
export const linesValid = (lines: BillLine[]) =>
  lines.every((l) => l.description.trim() && num.test(l.quantity) && parseFloat(l.quantity) > 0 && num.test(l.unit_price));
export const toPayloadLines = (lines: BillLine[]) =>
  lines.map((l) => ({
    description: l.description.trim(), quantity: l.quantity, unit_price: l.unit_price, discount_percent: l.discount_percent || "0",
    tax_rate_id: l.tax_rate_id || undefined, expense_account_id: l.expense_account_id || undefined,
  }));

/** Editable bill-style lines with a live total. Used by purchase orders and recurring bills. */
export function LinesEditor({ lines, setLines, currency }: { lines: BillLine[]; setLines: (l: BillLine[]) => void; currency: string }) {
  const taxes = useTaxRates();
  const accounts = useFinAccounts();
  const expenseAccounts = billAccounts(accounts.data ?? []).filter((a) => a.code !== "5900");
  const pct = (id: string | null) => parseFloat(taxes.data?.find((t) => t.id === id)?.percent ?? "0");
  const subtotal = lines.reduce((s, l) => s + lineNet(l), 0);
  const tax = lines.reduce((s, l) => s + Math.round(lineNet(l) * pct(l.tax_rate_id)) / 100, 0);
  const patch = (i: number, p: Partial<BillLine>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...p } : l)));
  return (
    <div className="space-y-2">
      {lines.map((l, i) => (
        <div key={i} className="grid gap-2 sm:grid-cols-[1fr_150px_60px_90px_60px_120px_auto]">
          <input aria-label={`Description ${i + 1}`} placeholder="Description" className={inp} value={l.description} onChange={(e) => patch(i, { description: e.target.value })} />
          <select aria-label={`Expense account ${i + 1}`} className={inp} value={l.expense_account_id ?? ""} onChange={(e) => patch(i, { expense_account_id: e.target.value || null })}>
            <option value="">Other Expenses</option>
            {expenseAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <input aria-label={`Quantity ${i + 1}`} inputMode="decimal" className={inp} value={l.quantity} onChange={(e) => patch(i, { quantity: e.target.value })} />
          <input aria-label={`Price ${i + 1}`} inputMode="decimal" placeholder="Price" className={inp} value={l.unit_price} onChange={(e) => patch(i, { unit_price: e.target.value })} />
          <input aria-label={`Discount ${i + 1}`} inputMode="decimal" placeholder="Disc %" className={inp} value={l.discount_percent} onChange={(e) => patch(i, { discount_percent: e.target.value })} />
          <select aria-label={`Tax ${i + 1}`} className={inp} value={l.tax_rate_id ?? ""} onChange={(e) => patch(i, { tax_rate_id: e.target.value || null })}>
            <option value="">No tax</option>
            {taxes.data?.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.percent}%)</option>)}
          </select>
          <button aria-label={`Remove line ${i + 1}`} disabled={lines.length === 1} className="justify-self-start p-2 disabled:opacity-30" onClick={() => setLines(lines.filter((_, j) => j !== i))}><Trash2 size={16} /></button>
        </div>
      ))}
      <Button variant="outline" size="sm" icon={<Plus size={14} />} onClick={() => setLines([...lines, blankLine()])}>Add line</Button>
      <p className="text-right text-sm font-semibold" data-testid="lines-total">Total {formatMoney(subtotal + tax, currency)}</p>
    </div>
  );
}

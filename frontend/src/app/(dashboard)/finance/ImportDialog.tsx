"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/atoms";
import { apiErrorMessage } from "@/services/payroll.service";
import {
  financeKeys, formatMoney, importTransactions, isMoneyAccount,
  type FinAccount, type ImportPreview,
} from "@/services/finance.service";

const inp =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]";

export function ImportDialog({ accounts, currency, onClose }: { accounts: FinAccount[]; currency: string; onClose: () => void }) {
  const qc = useQueryClient();
  const money = accounts.filter(isMoneyAccount);
  const fileRef = useRef<HTMLInputElement>(null);
  const [type, setType] = useState<"income" | "expense">("expense");
  const [accountId, setAccountId] = useState(money[0]?.id ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [dateOrder, setDateOrder] = useState<"mdy" | "dmy" | undefined>(undefined);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(dryRun: boolean, order = dateOrder) {
    if (!file) return;
    setBusy(true);
    try {
      const res = await importTransactions({ file, type, accountId, dryRun, dateOrder: order });
      if (dryRun) {
        setPreview(res);
      } else {
        toast.success(`${res.imported} entries imported`);
        await qc.invalidateQueries({ queryKey: financeKeys.all });
        onClose();
      }
    } catch (e) {
      toast.error(apiErrorMessage(e, "Import failed"));
    } finally {
      setBusy(false);
    }
  }

  const reset = () => setPreview(null);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose} role="presentation">
      <div role="dialog" aria-modal="true" aria-label="Import from Excel" onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] p-5">
          <div>
            <h3 className="font-heading text-base font-semibold">Import from Excel</h3>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">Columns: Date, Amount, Description, Category. One sheet = income or expenses.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 hover:bg-[hsl(var(--secondary))]"><X size={16} /></button>
        </div>

        <div className="space-y-4 overflow-y-auto p-5">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="imp-type" className="mb-1 block text-xs font-medium">This file contains</label>
              <select id="imp-type" value={type} onChange={(e) => { setType(e.target.value as "income" | "expense"); reset(); }} className={inp}>
                <option value="expense">Expenses</option>
                <option value="income">Income</option>
              </select>
            </div>
            <div>
              <label htmlFor="imp-account" className="mb-1 block text-xs font-medium">{type === "income" ? "Received in" : "Paid from"}</label>
              <select id="imp-account" value={accountId} onChange={(e) => { setAccountId(e.target.value); reset(); }} className={inp}>
                {money.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label htmlFor="imp-file" className="mb-1 block text-xs font-medium">File (.xlsx or .csv)</label>
            <input id="imp-file" ref={fileRef} type="file" accept=".xlsx,.csv"
              onChange={(e) => { setFile(e.target.files?.[0] ?? null); reset(); }} className="block w-full text-sm" />
          </div>

          {preview && (
            <div className="space-y-3">
              <div className="rounded-lg bg-[hsl(var(--secondary))] p-3 text-sm">
                <p><strong>{preview.to_import}</strong> of {preview.total_rows} rows will be imported
                  {preview.duplicates > 0 && <> · {preview.duplicates} already imported</>}.</p>
                {preview.new_categories.length > 0 && (
                  <p className="mt-1">New categories to create: <strong>{preview.new_categories.join(", ")}</strong></p>
                )}
                <p className="mt-1 flex items-center gap-2">
                  Dates read as
                  <select aria-label="Date order" value={preview.date_order} className="rounded border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-1 py-0.5 text-xs"
                    onChange={(e) => { const o = e.target.value as "mdy" | "dmy"; setDateOrder(o); void run(true, o); }}>
                    <option value="mdy">month/day/year</option>
                    <option value="dmy">day/month/year</option>
                  </select>
                </p>
              </div>
              {preview.preview.length > 0 && (
                <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))]">
                  <table className="w-full text-sm">
                    <thead className="bg-[hsl(var(--secondary))] text-left text-xs"><tr>
                      <th className="px-3 py-2">Date</th><th className="px-3 py-2 text-right">Amount</th><th className="px-3 py-2">Description</th><th className="px-3 py-2">Category</th>
                    </tr></thead>
                    <tbody>{preview.preview.map((r) => (
                      <tr key={r.row} className="border-t border-[hsl(var(--border))]">
                        <td className="px-3 py-2 whitespace-nowrap">{r.date}</td>
                        <td className="px-3 py-2 text-right whitespace-nowrap">{formatMoney(r.amount, currency)}</td>
                        <td className="px-3 py-2">{r.description}</td><td className="px-3 py-2">{r.category}</td>
                      </tr>))}</tbody>
                  </table>
                </div>
              )}
              {preview.skipped.filter((s) => s.reason !== "already imported").length > 0 && (
                <details className="text-xs text-[hsl(var(--foreground-muted))]">
                  <summary className="cursor-pointer">{preview.skipped.filter((s) => s.reason !== "already imported").length} rows skipped</summary>
                  <ul className="mt-1 list-disc pl-5">
                    {preview.skipped.filter((s) => s.reason !== "already imported").map((s) => <li key={s.row}>Row {s.row}: {s.reason}</li>)}
                  </ul>
                </details>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-[hsl(var(--border))] p-4">
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          {preview ? (
            <Button size="sm" disabled={busy || preview.to_import === 0} onClick={() => void run(false)}>
              {busy ? "Importing…" : `Import ${preview.to_import} entries`}
            </Button>
          ) : (
            <Button size="sm" disabled={busy || !file || !accountId} onClick={() => void run(true)}>{busy ? "Checking…" : "Check file"}</Button>
          )}
        </div>
      </div>
    </div>
  );
}

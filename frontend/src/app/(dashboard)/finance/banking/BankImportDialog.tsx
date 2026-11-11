"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/atoms";
import { apiErrorMessage } from "@/services/payroll.service";
import { formatMoney } from "@/services/finance.service";
import { bankKeys, importStatement, type StatementImportResult } from "@/services/finance-banking.service";
import { Modal } from "../sales/CustomerDialog";

export function BankImportDialog({ accountId, accountName, currency, onClose }: { accountId: string; accountName: string; currency: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [order, setOrder] = useState<"mdy" | "dmy" | undefined>(undefined);
  const [res, setRes] = useState<StatementImportResult | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(dryRun: boolean, o = order) {
    if (!file) return;
    setBusy(true);
    try {
      const r = await importStatement({ file, accountId, dryRun, dateOrder: o });
      if (dryRun) { setRes(r); return; }
      toast.success(`${r.imported} lines imported, ${r.matched} matched automatically`);
      await qc.invalidateQueries({ queryKey: bankKeys.all });
      onClose();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Import failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Import bank statement" onClose={onClose} footer={<>
      <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
      {res ? (
        <Button size="sm" disabled={busy || res.to_import === 0} onClick={() => void run(false)}>{busy ? "Importing…" : `Import ${res.to_import} lines`}</Button>
      ) : (
        <Button size="sm" disabled={busy || !file} onClick={() => void run(true)}>{busy ? "Checking…" : "Check file"}</Button>
      )}
    </>}>
      <p className="text-xs text-[hsl(var(--foreground-muted))]">
        Into <strong>{accountName}</strong>. Columns: Date, Description, Debit and Credit (or one Amount column), Balance. Reference is optional. Lines already imported are skipped.
      </p>
      <div>
        <label htmlFor="bs-file" className="mb-1 block text-xs font-medium">Statement file (.xlsx or .csv)</label>
        <input id="bs-file" type="file" accept=".xlsx,.csv" className="block w-full text-sm" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setRes(null); }} />
      </div>
      {res && (
        <div className="space-y-3">
          <div className="rounded-lg bg-[hsl(var(--secondary))] p-3 text-sm">
            <p><strong>{res.to_import}</strong> of {res.total_rows} rows will be imported{res.duplicates > 0 && <> · {res.duplicates} already imported</>}.</p>
            <p className="mt-1 flex items-center gap-2">
              Dates read as
              <select aria-label="Date order" value={res.date_order} className="rounded border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-1 py-0.5 text-xs"
                onChange={(e) => { const o = e.target.value as "mdy" | "dmy"; setOrder(o); void run(true, o); }}>
                <option value="dmy">day/month/year</option>
                <option value="mdy">month/day/year</option>
              </select>
              {res.date_order_guessed && <span className="text-xs text-amber-600">Could not tell from the dates. Check the first rows.</span>}
            </p>
          </div>
          {res.preview.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))]">
              <table className="w-full text-sm">
                <thead className="bg-[hsl(var(--secondary))] text-left text-xs"><tr><th className="px-3 py-2">Date</th><th className="px-3 py-2">Description</th><th className="px-3 py-2 text-right">Amount</th></tr></thead>
                <tbody>{res.preview.map((r, i) => (
                  <tr key={i} className="border-t border-[hsl(var(--border))]">
                    <td className="whitespace-nowrap px-3 py-2">{r.date}</td>
                    <td className="px-3 py-2">{r.description}{r.duplicate && <span className="ml-2 text-xs text-[hsl(var(--foreground-muted))]">already imported</span>}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">{formatMoney(r.amount, currency)}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          )}
          {res.skipped.length > 0 && (
            <details className="text-xs text-[hsl(var(--foreground-muted))]">
              <summary className="cursor-pointer">{res.skipped.length} rows skipped</summary>
              <ul className="mt-1 list-disc pl-5">{res.skipped.map((s) => <li key={s.row}>Row {s.row}: {s.reason}</li>)}</ul>
            </details>
          )}
        </div>
      )}
    </Modal>
  );
}

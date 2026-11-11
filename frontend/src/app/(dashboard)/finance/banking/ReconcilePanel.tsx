"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button, Card, Skeleton } from "@/components/atoms";
import { apiErrorMessage } from "@/services/payroll.service";
import { formatMoney } from "@/services/finance.service";
import {
  checkReconciliation, useFinishReconciliation, useReconciliations, useUndoReconciliation, type ReconcileCheck,
} from "@/services/finance-banking.service";
import { today } from "@/services/finance-budget.service";
import { inp } from "../sales/CustomerDialog";

export function ReconcilePanel({ accountId, currency, canManage }: { accountId: string; currency: string; canManage: boolean }) {
  const [date, setDate] = useState(today());
  const [balance, setBalance] = useState("");
  const [beginning, setBeginning] = useState("");
  const [check, setCheck] = useState<ReconcileCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const recs = useReconciliations(accountId);
  const finish = useFinishReconciliation();
  const undo = useUndoReconciliation();

  const vars = () => ({ account_id: accountId, statement_date: date, statement_balance: balance,
    ...(beginning.trim() !== "" ? { beginning_balance: beginning } : {}) });
  const reset = () => setCheck(null);

  async function run() {
    setBusy(true);
    try { setCheck(await checkReconciliation(vars())); }
    catch (e) { setCheck(null); toast.error(apiErrorMessage(e, "Could not check the balance")); }
    finally { setBusy(false); }
  }

  const row = (label: string, value: string, testId?: string) => (
    <div className="flex justify-between py-1 text-sm"><span>{label}</span><span className="tabular-nums" data-testid={testId}>{formatMoney(value, currency)}</span></div>
  );
  const last = recs.data?.[0];

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card className="space-y-4 p-5">
        <h2 className="font-heading text-base font-semibold">Reconcile with your statement</h2>
        <div className="grid grid-cols-2 gap-3">
          <div><label htmlFor="rc-date" className="mb-1 block text-xs font-medium">Statement date</label>
            <input id="rc-date" type="date" className={inp} value={date} onChange={(e) => { setDate(e.target.value); reset(); }} /></div>
          <div><label htmlFor="rc-bal" className="mb-1 block text-xs font-medium">Statement ending balance</label>
            <input id="rc-bal" type="number" step="0.01" className={inp} value={balance} onChange={(e) => { setBalance(e.target.value); reset(); }} /></div>
        </div>
        {!last && (
          <div><label htmlFor="rc-begin" className="mb-1 block text-xs font-medium">Beginning balance (first time only)</label>
            <input id="rc-begin" type="number" step="0.01" className={inp} value={beginning} placeholder="From the statement's opening balance"
              onChange={(e) => { setBeginning(e.target.value); reset(); }} /></div>
        )}
        <Button size="sm" disabled={busy || !date || balance.trim() === ""} onClick={() => void run()}>{busy ? "Checking…" : "Check"}</Button>

        {check && (
          <div className="rounded-lg bg-[hsl(var(--secondary))] p-4">
            {row("Beginning balance", check.beginning_balance)}
            {row(`Matched lines (${check.cleared_count})`, check.cleared_total)}
            {row("Statement ending balance", check.statement_balance)}
            <div className="mt-1 border-t border-[hsl(var(--border))] pt-1">{row("Difference", check.difference, "difference")}</div>
            {check.unmatched_count > 0 && <p className="mt-2 text-xs text-amber-600">{check.unmatched_count} line(s) up to this date still need matching.</p>}
            {check.reason ? <p role="alert" className="mt-2 text-sm text-red-600">{check.reason}</p>
              : <p className="mt-2 text-sm text-green-700">Everything adds up.</p>}
            {canManage && (
              <Button size="sm" className="mt-3" disabled={!check.can_finish || finish.isPending}
                onClick={() => finish.mutate(vars(), { onSuccess: () => { reset(); setBalance(""); setBeginning(""); } })}>
                {finish.isPending ? "Finishing…" : "Finish reconciliation"}
              </Button>
            )}
          </div>
        )}
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 font-heading text-base font-semibold">Finished reconciliations</h2>
        {recs.isLoading ? <Skeleton className="h-20" /> : !recs.data?.length ? (
          <p className="text-sm text-[hsl(var(--foreground-muted))]">None yet.</p>
        ) : (
          <ul className="divide-y divide-[hsl(var(--border))]">
            {recs.data.map((r, i) => (
              <li key={r.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <div><p className="font-medium">{r.statement_date}</p>
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">{r.line_count} lines · ending {formatMoney(r.statement_balance, currency)}</p></div>
                {canManage && i === 0 && <Button variant="outline" size="sm" disabled={undo.isPending} onClick={() => undo.mutate(r.id)}>Undo</Button>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

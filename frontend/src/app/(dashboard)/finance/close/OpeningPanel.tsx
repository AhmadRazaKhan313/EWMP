"use client";

import { useMemo, useState } from "react";
import { Button, Card, Skeleton } from "@/components/atoms";
import { cn } from "@/utils/cn";
import { formatMoney, useFinAccounts } from "@/services/finance.service";
import { useClearOpening, useOpeningBalances, useSaveOpening, type OpeningBalances } from "@/services/finance-close.service";
import { Modal, inp } from "../sales/CustomerDialog";

const th = "px-3 py-2 text-left text-xs font-semibold text-[hsl(var(--foreground-muted))]";
const td = "px-3 py-2 text-sm";
const SECTIONS = [["asset", "Assets"], ["liability", "Liabilities"], ["equity", "Equity"]] as const;

function Form({ initial, currency, canManage }: { initial: OpeningBalances; currency: string; canManage: boolean }) {
  const accounts = useFinAccounts();
  const save = useSaveOpening();
  const clear = useClearOpening();
  const [asOf, setAsOf] = useState(initial.as_of ?? "");
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(initial.items.map((i) => [i.account_id, i.amount])));
  const [confirmClear, setConfirmClear] = useState(false);

  // Only leaf balance-sheet accounts; the plug account is calculated for you.
  const list = useMemo(() => {
    const all = accounts.data ?? [];
    const parents = new Set(all.map((a) => a.parent_id).filter(Boolean));
    return all.filter((a) => a.is_active && !parents.has(a.id) && a.code !== "3020" && ["asset", "liability", "equity"].includes(a.type));
  }, [accounts.data]);

  const entered = list.filter((a) => (vals[a.id] ?? "").trim() !== "" && Number(vals[a.id]) !== 0 && Number.isFinite(Number(vals[a.id])));
  const debit = entered.reduce((s, a) => s + (a.type === "asset" ? Number(vals[a.id]) : 0), 0);
  const credit = entered.reduce((s, a) => s + (a.type === "asset" ? 0 : Number(vals[a.id])), 0);
  const plug = Math.round((debit - credit) * 100) / 100;
  const hasEntry = !!initial.as_of;

  if (accounts.isLoading) return <Skeleton className="h-48" />;

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-5">
        <p className="text-sm text-[hsl(var(--foreground-muted))]">
          Enter what each account held on the day you started using the books. Whatever is left over goes to <strong>Opening Balance Equity</strong> automatically, so the books always balance.
        </p>
        <div className="max-w-xs"><label htmlFor="ob-date" className="mb-1 block text-xs font-medium">Balances as of</label>
          <input id="ob-date" type="date" className={inp} value={asOf} disabled={!canManage} onChange={(e) => setAsOf(e.target.value)} /></div>
        {hasEntry && <p className="text-xs text-[hsl(var(--foreground-muted))]">Saved as {initial.entry_number}. Saving again replaces it.</p>}
      </Card>

      {SECTIONS.map(([type, title]) => {
        const rows = list.filter((a) => a.type === type);
        if (!rows.length) return null;
        return (
          <Card key={type} className="overflow-x-auto p-0">
            <h2 className="px-4 pt-4 font-heading text-base font-semibold">{title}</h2>
            <table className="w-full" aria-label={title}>
              <thead><tr><th className={th}>Account</th><th className={cn(th, "w-48 text-right")}>Balance ({currency})</th></tr></thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id} className="border-t border-[hsl(var(--border))]">
                    <td className={td}>{a.name} <span className="text-xs text-[hsl(var(--foreground-muted))]">{a.code}</span></td>
                    <td className={td}>
                      <input aria-label={a.name} type="number" step="0.01" className={cn(inp, "text-right")} value={vals[a.id] ?? ""} disabled={!canManage}
                        onChange={(e) => setVals((v) => ({ ...v, [a.id]: e.target.value }))} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        );
      })}

      <Card className="flex flex-wrap items-center justify-between gap-3 p-5">
        <div>
          <p className="text-xs text-[hsl(var(--foreground-muted))]">Opening Balance Equity (calculated)</p>
          <p className="font-heading text-lg font-semibold tabular-nums" data-testid="plug">{formatMoney(String(-plug), currency)}</p>
        </div>
        {canManage && (
          <div className="flex gap-2">
            {hasEntry && <Button variant="outline" size="sm" disabled={clear.isPending} onClick={() => setConfirmClear(true)}>Remove</Button>}
            <Button size="sm" disabled={!asOf || entered.length === 0 || save.isPending}
              onClick={() => save.mutate({ as_of: asOf, items: entered.map((a) => ({ account_id: a.id, amount: vals[a.id]!.trim() })) })}>
              {save.isPending ? "Saving…" : "Save opening balances"}
            </Button>
          </div>
        )}
      </Card>

      {confirmClear && (
        <Modal title="Remove opening balances?" onClose={() => setConfirmClear(false)} footer={<>
          <Button variant="outline" size="sm" onClick={() => setConfirmClear(false)}>Cancel</Button>
          <Button size="sm" disabled={clear.isPending} onClick={() => clear.mutate(undefined, { onSuccess: () => setConfirmClear(false) })}>Remove</Button>
        </>}>
          <p className="text-sm">The opening entry is reversed. Nothing else in your books changes.</p>
        </Modal>
      )}
    </div>
  );
}

export function OpeningPanel({ currency, canManage }: { currency: string; canManage: boolean }) {
  const opening = useOpeningBalances();
  if (opening.isLoading || !opening.data) return <Skeleton className="h-48" />;
  return <Form key={opening.data.entry_number ?? "none"} initial={opening.data} currency={currency} canManage={canManage} />;
}

"use client";

import { useState } from "react";
import { Download, Plus, Upload, Wallet, Ban } from "lucide-react";
import { Button, Card, EmptyState, PageHeader, Skeleton, Tabs } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import {
  downloadFinanceExcel, formatMoney, useCreateAccount, useFinAccounts, useFinSummary,
  useFinTransactions, useSetupFinance, useVoidTransaction,
  type CategoryTotal, type FinSummary, type MoneyKind, type TxnType,
} from "@/services/finance.service";
import { cn } from "@/utils/cn";
import { AddEntryDialog } from "./AddEntryDialog";
import { ImportDialog } from "./ImportDialog";

type Tab = "expense" | "income" | "balance";

function StatCard({ label, value, tone }: { label: string; value: string; tone: "income" | "expense" | "balance" }) {
  return (
    <Card className={cn(tone === "balance" && "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]")}>
      <p className={cn("text-sm", tone !== "balance" && "text-[hsl(var(--foreground-muted))]")}>{label}</p>
      <p className="mt-1 text-2xl font-semibold" data-testid={`stat-${tone}`}>{value}</p>
    </Card>
  );
}

function Bars({ title, rows, total, currency }: { title: string; rows: CategoryTotal[]; total: string; currency: string }) {
  const max = Math.max(1, ...rows.map((r) => parseFloat(r.total)));
  return (
    <Card className="space-y-4">
      <h2 className="font-heading text-lg font-semibold">{title}</h2>
      {rows.length === 0 && <p className="text-sm text-[hsl(var(--foreground-muted))]">Nothing yet.</p>}
      {rows.map((r) => (
        <div key={r.category_id} className="space-y-1.5">
          <div className="flex justify-between gap-3 text-sm"><span>{r.category}</span><span className="font-semibold">{formatMoney(r.total, currency)}</span></div>
          <div className="h-2.5 rounded-full bg-[hsl(var(--secondary))]">
            <div className="h-2.5 rounded-full bg-[hsl(var(--primary))]" style={{ width: `${(parseFloat(r.total) / max) * 100}%` }} />
          </div>
        </div>
      ))}
      <div className="flex justify-between border-t border-[hsl(var(--border))] pt-3 font-semibold">
        <span>Total {title.toLowerCase()}</span><span>{formatMoney(total, currency)}</span>
      </div>
    </Card>
  );
}

function MoneyAccounts({ summary, canManage }: { summary: FinSummary; canManage: boolean }) {
  const create = useCreateAccount();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<MoneyKind>("bank");
  return (
    <Card className="space-y-3">
      <h2 className="font-heading text-lg font-semibold">Accounts</h2>
      {summary.money_accounts.map((a) => (
        <div key={a.account_id} className="flex justify-between text-sm"><span>{a.name}</span><span className="font-semibold">{formatMoney(a.balance, summary.currency)}</span></div>
      ))}
      {canManage && (
        <form className="flex gap-2 border-t border-[hsl(var(--border))] pt-3"
          onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate({ name: name.trim(), type: "asset", money_kind: kind }, { onSuccess: () => setName("") }); }}>
          <input aria-label="New account name" placeholder="New account, e.g. Faysal Bank" value={name} onChange={(e) => setName(e.target.value)}
            className="min-w-0 flex-1 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm" />
          <select aria-label="Account kind" value={kind} onChange={(e) => setKind(e.target.value as MoneyKind)}
            className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 py-2 text-sm">
            <option value="bank">Bank</option><option value="wallet">Mobile wallet</option><option value="cash">Cash</option>
          </select>
          <Button type="submit" size="sm" disabled={!name.trim() || create.isPending}>Add account</Button>
        </form>
      )}
    </Card>
  );
}

export default function FinancePage() {
  const { hasPermission } = useAuthStore();
  const canPost = hasPermission("finance.post");
  const canVoid = hasPermission("finance.void");
  const canExport = hasPermission("finance.export");
  const canManage = hasPermission("finance.manage");

  const [tab, setTab] = useState<Tab>("expense");
  const [category, setCategory] = useState<string | undefined>(undefined);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);

  const accounts = useFinAccounts();
  const summary = useFinSummary();
  const txType: TxnType | undefined = tab === "balance" ? undefined : tab;
  const txns = useFinTransactions(txType, category);
  const setup = useSetupFinance();
  const voidTxn = useVoidTransaction();

  const currency = summary.data?.currency ?? "PKR";
  const needsSetup = accounts.isSuccess && accounts.data.length === 0;

  if (needsSetup) {
    return (
      <div className="space-y-6">
        <PageHeader title="Finance" />
        <EmptyState icon={Wallet} title="Set up your books"
          description="Creates a starting chart of accounts (Cash, Bank, Mobile Wallet, Salary, Utilities…) for this organization. You can add more later."
          action={canManage ? <Button onClick={() => setup.mutate()} disabled={setup.isPending}>Set up finance</Button> : undefined} />
      </div>
    );
  }

  const chips: { id?: string; label: string }[] = [
    { id: undefined, label: "All" },
    ...((tab === "income" ? summary.data?.income_by_category : summary.data?.expense_by_category) ?? [])
      .map((c) => ({ id: c.category_id, label: c.category })),
  ];
  const rows = txns.data?.items ?? [];
  const shownTotal = rows.reduce((s, r) => s + parseFloat(r.amount), 0);
  const s = summary.data;

  return (
    <div className="space-y-6">
      <PageHeader title="Finance"
        action={
          <div className="flex flex-wrap gap-2">
            {canExport && <Button variant="outline" icon={<Download size={15} />} onClick={() => void downloadFinanceExcel()}>Download Excel</Button>}
            {canPost && <Button variant="outline" icon={<Upload size={15} />} onClick={() => setImporting(true)}>Import</Button>}
            {canPost && <Button icon={<Plus size={15} />} onClick={() => setAdding(true)}>Add entry</Button>}
          </div>
        } />

      <div className="grid gap-4 sm:grid-cols-3">
        {summary.isLoading || !s ? (
          Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24" />)
        ) : (
          <>
            <StatCard label="Income" tone="income" value={formatMoney(s.income_total, currency)} />
            <StatCard label="Expenses" tone="expense" value={formatMoney(s.expense_total, currency)} />
            <StatCard label="Balance" tone="balance" value={formatMoney(s.balance, currency)} />
          </>
        )}
      </div>

      <Tabs<Tab> active={tab} onChange={(t) => { setTab(t); setCategory(undefined); }}
        tabs={[{ value: "expense", label: "Expenses" }, { value: "income", label: "Income" }, { value: "balance", label: "Balance" }]} />

      {tab !== "balance" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {chips.map((c) => (
              <button key={c.id ?? "all"} type="button" aria-pressed={category === c.id} onClick={() => setCategory(c.id)}
                className={cn("rounded-full border px-3 py-1 text-sm font-medium transition-colors",
                  category === c.id ? "border-transparent bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]" : "border-[hsl(var(--border))] hover:bg-[hsl(var(--secondary))]")}>
                {c.label}
              </button>
            ))}
          </div>

          <Card padding={false} className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[680px] text-sm">
                <thead className="bg-[hsl(var(--primary))] text-left text-[hsl(var(--primary-foreground))]">
                  <tr>
                    <th className="px-4 py-3.5 font-semibold">Date</th>
                    <th className="px-4 py-3.5 text-right font-semibold">Amount</th>
                    <th className="px-4 py-3.5 font-semibold">Description</th>
                    <th className="px-4 py-3.5 font-semibold">Category</th>
                    {canVoid && <th className="w-12 px-2 py-3.5"><span className="sr-only">Actions</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {txns.isLoading && <tr><td colSpan={5} className="p-4"><Skeleton className="h-8" /></td></tr>}
                  {!txns.isLoading && rows.length === 0 && (
                    <tr><td colSpan={5} className="px-4 py-10 text-center text-[hsl(var(--foreground-muted))]">No entries yet.</td></tr>
                  )}
                  {rows.map((r) => (
                    <tr key={r.id} className="border-t border-[hsl(var(--border))]">
                      <td className="whitespace-nowrap px-4 py-3.5 text-[hsl(var(--foreground-muted))]">{r.date}</td>
                      <td className="whitespace-nowrap px-4 py-3.5 text-right font-semibold">{formatMoney(r.amount, currency)}</td>
                      <td className="px-4 py-3.5">
                        {r.description}
                        {(r.payment_provider || r.payment_tid) && (
                          <div className="text-xs text-[hsl(var(--foreground-muted))]">
                            {[r.payment_provider, r.payment_account_no, r.payment_tid && `TID ${r.payment_tid}`].filter(Boolean).join(" · ")}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3.5">
                        <span className="font-semibold text-[hsl(var(--accent-foreground))]">{r.category}</span>
                        <span className="block text-xs text-[hsl(var(--foreground-muted))]">{r.account}</span>
                      </td>
                      {canVoid && (
                        <td className="px-2 py-3.5">
                          <button type="button" aria-label={`Void ${r.number}`} title="Void this entry" disabled={voidTxn.isPending}
                            onClick={() => { if (confirm(`Void ${r.number}? A reversing entry is posted; the original stays in the journal.`)) voidTxn.mutate(r.id); }}
                            className="rounded p-1.5 text-[hsl(var(--destructive))] hover:bg-[hsl(var(--status-error-bg))]"><Ban size={14} /></button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
                {rows.length > 0 && (
                  <tfoot className="bg-[hsl(var(--secondary))] font-semibold">
                    <tr>
                      <td className="px-4 py-3.5">Total</td>
                      <td className="px-4 py-3.5 text-right" data-testid="shown-total">{formatMoney(shownTotal, currency)}</td>
                      <td className="px-4 py-3.5 font-normal text-[hsl(var(--foreground-muted))]" colSpan={canVoid ? 3 : 2}>
                        {rows.length} {rows.length === 1 ? "entry" : "entries"}{txns.data && txns.data.total > rows.length ? ` of ${txns.data.total}` : ""}
                      </td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </Card>
        </div>
      )}

      {tab === "balance" && s && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Bars title="Income" rows={s.income_by_category} total={s.income_total} currency={currency} />
          <Bars title="Expenses" rows={s.expense_by_category} total={s.expense_total} currency={currency} />
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-[hsl(var(--primary))] px-6 py-5 text-[hsl(var(--primary-foreground))] lg:col-span-2">
            <span className="font-semibold">Balance (income minus expenses)</span>
            <span className="text-2xl font-semibold">{formatMoney(s.balance, currency)}</span>
          </div>
          <div className="lg:col-span-2"><MoneyAccounts summary={s} canManage={canManage} /></div>
        </div>
      )}

      {adding && accounts.data && <AddEntryDialog accounts={accounts.data} defaultType={tab === "income" ? "income" : "expense"} onClose={() => setAdding(false)} />}
      {importing && accounts.data && <ImportDialog accounts={accounts.data} currency={currency} onClose={() => setImporting(false)} />}
    </div>
  );
}

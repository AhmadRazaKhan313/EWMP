"use client";

import { useEffect, useState } from "react";
import { Landmark, Upload, Wand2 } from "lucide-react";
import { Button, Card, EmptyState, PageHeader, Skeleton, Tabs } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { cn } from "@/utils/cn";
import { formatMoney, isMoneyAccount, useFinAccounts, useFinSummary } from "@/services/finance.service";
import {
  useAutoMatch, useBankLines, useIgnoreLine, useRestoreLine, useUnmatchLine, type BankLine, type LineStatus,
} from "@/services/finance-banking.service";
import { BankImportDialog } from "./BankImportDialog";
import { BookDialog, MatchDialog } from "./BankLineDialogs";
import { ReconcilePanel } from "./ReconcilePanel";

type Tab = "lines" | "reconcile";
const th = "px-3 py-2 text-left text-xs font-semibold text-[hsl(var(--foreground-muted))]";
const td = "px-3 py-2 text-sm";
const STATUS_LABEL: Record<LineStatus | "", string> = { "": "All", unmatched: "Unmatched", matched: "Matched", ignored: "Ignored" };

export default function BankingPage() {
  const canPost = useAuthStore((s) => s.hasPermission("finance.post"));
  const canManage = useAuthStore((s) => s.hasPermission("finance.manage"));
  const accounts = useFinAccounts();
  const summary = useFinSummary();
  const currency = summary.data?.currency ?? "PKR";
  const money = (accounts.data ?? []).filter((a) => isMoneyAccount(a) && a.is_active);

  const [tab, setTab] = useState<Tab>("lines");
  const [accountId, setAccountId] = useState("");
  const [status, setStatus] = useState<LineStatus | "">("unmatched");
  const [q, setQ] = useState("");
  const [importing, setImporting] = useState(false);
  const [matching, setMatching] = useState<BankLine | null>(null);
  const [booking, setBooking] = useState<BankLine | null>(null);

  useEffect(() => { if (!accountId && money.length) setAccountId(money[0]!.id); }, [accountId, money]);

  const lines = useBankLines(accountId, status, q);
  const auto = useAutoMatch();
  const unmatch = useUnmatchLine();
  const ignore = useIgnoreLine();
  const restore = useRestoreLine();
  const account = money.find((a) => a.id === accountId);
  const counts = lines.data?.counts;
  const total = counts ? counts.unmatched + counts.matched + counts.ignored : 0;

  const actions = (l: BankLine) => {
    if (l.reconciled) return <span className="text-xs text-[hsl(var(--foreground-muted))]">Reconciled</span>;
    if (!canPost) return null;
    if (l.status === "unmatched") return (
      <div className="flex justify-end gap-1">
        <Button variant="outline" size="sm" onClick={() => setMatching(l)}>Match</Button>
        <Button variant="outline" size="sm" onClick={() => setBooking(l)}>Book</Button>
        <Button variant="ghost" size="sm" onClick={() => ignore.mutate(l.id)}>Ignore</Button>
      </div>
    );
    if (l.status === "matched") return <div className="flex justify-end"><Button variant="outline" size="sm" onClick={() => unmatch.mutate(l.id)}>Unmatch</Button></div>;
    return <div className="flex justify-end"><Button variant="outline" size="sm" onClick={() => restore.mutate(l.id)}>Restore</Button></div>;
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Banking"
        action={canPost && accountId && (
          <div className="flex gap-2">
            <Button variant="outline" icon={<Wand2 size={15} />} disabled={auto.isPending} onClick={() => auto.mutate(accountId)}>Auto-match</Button>
            <Button icon={<Upload size={15} />} onClick={() => setImporting(true)}>Import statement</Button>
          </div>
        )} />

      {accounts.isLoading ? <Skeleton className="h-10" /> : money.length === 0 ? (
        <EmptyState icon={Landmark} title="No cash, bank or wallet account yet" description="Add one in Finance first, then import its statement here." />
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <Tabs<Tab> active={tab} onChange={setTab} tabs={[{ value: "lines", label: "Statement lines" }, { value: "reconcile", label: "Reconcile" }]} />
            <div>
              <label htmlFor="bk-account" className="mb-1 block text-xs font-medium">Account</label>
              <select id="bk-account" value={accountId} onChange={(e) => setAccountId(e.target.value)}
                className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm">
                {money.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
          </div>

          {tab === "lines" && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                {(["unmatched", "matched", "ignored", ""] as const).map((s) => (
                  <button key={s || "all"} type="button" aria-pressed={status === s} onClick={() => setStatus(s)}
                    className={cn("rounded-full border px-3 py-1 text-xs", status === s ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]" : "border-[hsl(var(--border))]")}>
                    {STATUS_LABEL[s]}{counts ? ` (${s === "" ? total : counts[s]})` : ""}
                  </button>
                ))}
                <input aria-label="Search lines" placeholder="Search description or reference" value={q} onChange={(e) => setQ(e.target.value)}
                  className="ml-auto w-64 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1.5 text-sm" />
              </div>

              {lines.isLoading || (!lines.data && !lines.isError) ? <Skeleton className="h-48" /> : !lines.data?.items.length ? (
                <EmptyState icon={Landmark} title={total === 0 ? "No statement imported yet" : "No lines here"}
                  description={total === 0 ? "Import the bank or wallet statement to start matching it with your books." : "Try another filter."} />
              ) : (
                <Card className="overflow-x-auto p-0">
                  <table className="w-full" aria-label="Statement lines">
                    <thead><tr><th className={th}>Date</th><th className={th}>Description</th><th className={cn(th, "text-right")}>Amount</th><th className={th}>Matched to</th><th className={th} /></tr></thead>
                    <tbody>
                      {lines.data.items.map((l) => (
                        <tr key={l.id} className="border-t border-[hsl(var(--border))]">
                          <td className={cn(td, "whitespace-nowrap")}>{l.date}</td>
                          <td className={td}>{l.description}{l.reference && <span className="ml-2 text-xs text-[hsl(var(--foreground-muted))]">{l.reference}</span>}</td>
                          <td className={cn(td, "whitespace-nowrap text-right tabular-nums", parseFloat(l.amount) < 0 ? "text-red-600" : "text-green-700")}>{formatMoney(l.amount, currency)}</td>
                          <td className={td}>
                            {l.match ? <>{l.match.number}{l.match.voided && <span className="ml-2 text-xs text-red-600">entry voided</span>}</>
                              : l.status === "ignored" ? <span className="text-xs text-[hsl(var(--foreground-muted))]">Ignored</span> : "—"}
                          </td>
                          <td className={td}>{actions(l)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              )}
            </>
          )}

          {tab === "reconcile" && accountId && <ReconcilePanel key={accountId} accountId={accountId} currency={currency} canManage={canManage} />}
        </>
      )}

      {importing && account && <BankImportDialog accountId={account.id} accountName={account.name} currency={currency} onClose={() => setImporting(false)} />}
      {matching && <MatchDialog line={matching} currency={currency} onClose={() => setMatching(null)} />}
      {booking && <BookDialog line={booking} accounts={accounts.data ?? []} currency={currency} onClose={() => setBooking(null)} />}
    </div>
  );
}

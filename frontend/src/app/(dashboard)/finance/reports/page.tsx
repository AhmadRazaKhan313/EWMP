"use client";

import { useMemo, useState } from "react";
import { BookOpen, CheckCircle2, Download } from "lucide-react";
import { Button, Card, EmptyState, PageHeader, Skeleton, Tabs } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { formatMoney, useFinAccounts, useFinSummary } from "@/services/finance.service";
import {
  BUCKETS, PRESET_LABEL, exportReport, presetRange, ymd, useAging, useBalanceSheet, useGeneralLedger, useProfitLoss, useTrialBalanceReport,
  type Aging, type Preset, type ReportName,
} from "@/services/finance-reports.service";
import { cn } from "@/utils/cn";

type Tab = "pl" | "bs" | "tb" | "ar" | "ap" | "gl";
const th = "px-3 py-2 text-left text-xs font-semibold text-[hsl(var(--foreground-muted))]";
const td = "px-3 py-2 text-sm";
const num = "text-right tabular-nums";
const input = "rounded-md border border-[hsl(var(--border))] bg-transparent px-3 py-2 text-sm";
const neg = (v: string) => (parseFloat(v) < 0 ? "text-red-600" : "");

function Section({ title, rows, total, cur, prevTotal, compare }: {
  title: string; rows: { account_id: string; code: string; name: string; amount: string; previous?: string }[]; total: string; cur: string; prevTotal?: string; compare: boolean;
}) {
  return (
    <>
      <tr className="bg-[hsl(var(--muted))]"><td colSpan={compare ? 4 : 3} className="px-3 py-2 text-xs font-semibold uppercase tracking-wide">{title}</td></tr>
      {rows.map((r) => (
        <tr key={r.account_id} className="border-t border-[hsl(var(--border))]">
          <td className={cn(td, "w-24 text-[hsl(var(--foreground-muted))]")}>{r.code}</td><td className={td}>{r.name}</td>
          <td className={cn(td, num, neg(r.amount))}>{formatMoney(r.amount, cur)}</td>
          {compare && <td className={cn(td, num, "text-[hsl(var(--foreground-muted))]")}>{formatMoney(r.previous ?? "0", cur)}</td>}
        </tr>
      ))}
      <tr className="border-t border-[hsl(var(--border))] font-semibold">
        <td className={td} /><td className={td}>Total {title.toLowerCase()}</td>
        <td className={cn(td, num)}>{formatMoney(total, cur)}</td>
        {compare && <td className={cn(td, num)}>{formatMoney(prevTotal ?? "0", cur)}</td>}
      </tr>
    </>
  );
}

function AgingTable({ data }: { data: Aging }) {
  if (data.rows.length === 0) return <EmptyState icon={CheckCircle2} title="Nothing outstanding" description="No open documents right now." />;
  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full">
        <thead><tr><th className={th}>Name</th>{BUCKETS.map((b) => <th key={b.key} className={cn(th, "text-right")}>{b.label}</th>)}<th className={cn(th, "text-right")}>Total</th></tr></thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.party_id} className="border-t border-[hsl(var(--border))]">
              <td className={cn(td, "font-medium")}>{r.name}</td>
              {BUCKETS.map((b) => <td key={b.key} className={cn(td, num)}>{parseFloat(r[b.key]) ? formatMoney(r[b.key], data.currency) : "—"}</td>)}
              <td className={cn(td, num, "font-semibold")}>{formatMoney(r.total, data.currency)}</td>
            </tr>
          ))}
          <tr className="border-t-2 border-[hsl(var(--border))] font-semibold">
            <td className={td}>Total</td>
            {BUCKETS.map((b) => <td key={b.key} className={cn(td, num)}>{formatMoney(data.totals[b.key], data.currency)}</td>)}
            <td className={cn(td, num)}>{formatMoney(data.totals.total, data.currency)}</td>
          </tr>
        </tbody>
      </table>
    </Card>
  );
}

export default function ReportsPage() {
  const { hasPermission } = useAuthStore();
  const canExport = hasPermission("finance.export");
  const base = useFinSummary().data?.currency ?? "PKR";
  const accounts = useFinAccounts();
  const [tab, setTab] = useState<Tab>("pl");
  const [preset, setPreset] = useState<Preset>("this_year");
  const initial = useMemo(() => presetRange("this_year"), []);
  const [from, setFrom] = useState(initial.from);
  const [to, setTo] = useState(initial.to);
  const [asOf, setAsOf] = useState(ymd(new Date()));
  const [compare, setCompare] = useState(false);
  const [accountId, setAccountId] = useState("");

  const rangeBad = !!from && !!to && from > to;
  const pl = useProfitLoss({ date_from: from, date_to: to, compare }, tab === "pl" && !rangeBad);
  const bs = useBalanceSheet(asOf, tab === "bs");
  const tb = useTrialBalanceReport(asOf, tab === "tb");
  const ar = useAging("receivables", tab === "ar");
  const ap = useAging("payables", tab === "ap");
  const gl = useGeneralLedger({ account_id: accountId, date_from: from, date_to: to }, tab === "gl" && !rangeBad);

  const pick = (p: Preset) => {
    setPreset(p);
    if (p !== "custom") { const r = presetRange(p); setFrom(r.from); setTo(r.to); }
  };
  const usesRange = tab === "pl" || tab === "gl";
  const usesAsOf = tab === "bs" || tab === "tb";
  const doExport = (format: "xlsx" | "csv") => {
    const report: ReportName = ({ pl: "profit-loss", bs: "balance-sheet", tb: "trial-balance", ar: "receivables-aging", ap: "payables-aging", gl: "general-ledger" } as const)[tab];
    const params = tab === "pl" ? { date_from: from, date_to: to, compare } : tab === "gl" ? { account_id: accountId, date_from: from, date_to: to }
      : usesAsOf ? { as_of: asOf } : {};
    void exportReport(report, format, params);
  };
  const canDoExport = canExport && !(tab === "gl" && !accountId) && !rangeBad;

  return (
    <div className="space-y-6">
      <PageHeader title="Reports"
        action={canExport && (
          <div className="flex gap-2">
            <Button variant="outline" icon={<Download size={15} />} disabled={!canDoExport} onClick={() => doExport("xlsx")}>Excel</Button>
            <Button variant="outline" icon={<Download size={15} />} disabled={!canDoExport} onClick={() => doExport("csv")}>CSV</Button>
          </div>
        )} />

      <Tabs<Tab> active={tab} onChange={setTab} tabs={[
        { value: "pl", label: "Profit & Loss" }, { value: "bs", label: "Balance Sheet" }, { value: "tb", label: "Trial Balance" },
        { value: "ar", label: "Receivables" }, { value: "ap", label: "Payables" }, { value: "gl", label: "General Ledger" },
      ]} />

      {usesRange && (
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="rp-preset" className="mb-1 block text-xs font-medium">Period</label>
            <select id="rp-preset" className={input} value={preset} onChange={(e) => pick(e.target.value as Preset)}>
              {(Object.keys(PRESET_LABEL) as Preset[]).map((p) => <option key={p} value={p}>{PRESET_LABEL[p]}</option>)}
            </select>
          </div>
          <div><label htmlFor="rp-from" className="mb-1 block text-xs font-medium">From</label><input id="rp-from" type="date" className={input} value={from} onChange={(e) => { setFrom(e.target.value); setPreset("custom"); }} /></div>
          <div><label htmlFor="rp-to" className="mb-1 block text-xs font-medium">To</label><input id="rp-to" type="date" className={input} value={to} onChange={(e) => { setTo(e.target.value); setPreset("custom"); }} /></div>
          {tab === "pl" && <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />Compare with the period before</label>}
          {tab === "gl" && (
            <div>
              <label htmlFor="rp-acc" className="mb-1 block text-xs font-medium">Account</label>
              <select id="rp-acc" className={input} value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                <option value="">Select…</option>
                {accounts.data?.filter((a) => a.is_active).map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
              </select>
            </div>
          )}
        </div>
      )}
      {usesAsOf && (
        <div><label htmlFor="rp-asof" className="mb-1 block text-xs font-medium">As of</label><input id="rp-asof" type="date" className={input} value={asOf} onChange={(e) => setAsOf(e.target.value)} /></div>
      )}
      {rangeBad && <p role="alert" className="text-sm text-red-600">The “From” date is after the “To” date.</p>}

      {tab === "pl" && !rangeBad && (pl.isLoading || !pl.data ? <Skeleton className="h-48" /> : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full">
            <thead><tr><th className={th}>Code</th><th className={th}>Account</th><th className={cn(th, "text-right")}>{pl.data.date_from} – {pl.data.date_to}</th>
              {compare && <th className={cn(th, "text-right")}>{pl.data.previous_from} – {pl.data.previous_to}</th>}</tr></thead>
            <tbody>
              <Section title="Income" rows={pl.data.income.rows} total={pl.data.income.total} prevTotal={pl.data.income.previous_total} cur={pl.data.currency} compare={compare} />
              <Section title="Expenses" rows={pl.data.expenses.rows} total={pl.data.expenses.total} prevTotal={pl.data.expenses.previous_total} cur={pl.data.currency} compare={compare} />
              <tr className="border-t-2 border-[hsl(var(--border))] text-base font-bold">
                <td className={td} /><td className={td}>Net profit</td>
                <td className={cn(td, num, neg(pl.data.net_profit))} data-testid="net-profit">{formatMoney(pl.data.net_profit, pl.data.currency)}</td>
                {compare && <td className={cn(td, num)}>{formatMoney(pl.data.previous_net_profit ?? "0", pl.data.currency)}</td>}
              </tr>
            </tbody>
          </table>
        </Card>
      ))}

      {tab === "bs" && (bs.isLoading || !bs.data ? <Skeleton className="h-48" /> : (
        <div className="space-y-3">
          {!bs.data.balanced && <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">The balance sheet does not balance. Check the journal for one-sided entries.</p>}
          <Card className="overflow-x-auto p-0">
            <table className="w-full"><tbody>
              <Section title="Assets" rows={bs.data.assets.rows} total={bs.data.assets.total} cur={bs.data.currency} compare={false} />
              <Section title="Liabilities" rows={bs.data.liabilities.rows} total={bs.data.liabilities.total} cur={bs.data.currency} compare={false} />
              <Section title="Equity" rows={[...bs.data.equity.rows, { account_id: "profit", code: "", name: "Profit to date (not yet closed)", amount: bs.data.equity.profit_to_date }]}
                total={bs.data.equity.total} cur={bs.data.currency} compare={false} />
              <tr className="border-t-2 border-[hsl(var(--border))] font-bold">
                <td className={td} /><td className={td}>Total liabilities and equity</td>
                <td className={cn(td, num)} data-testid="bs-le">{formatMoney(bs.data.liabilities_and_equity, bs.data.currency)}</td>
              </tr>
            </tbody></table>
          </Card>
        </div>
      ))}

      {tab === "tb" && (tb.isLoading || !tb.data ? <Skeleton className="h-48" /> : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full">
            <thead><tr><th className={th}>Code</th><th className={th}>Account</th><th className={th}>Type</th><th className={cn(th, "text-right")}>Debit</th><th className={cn(th, "text-right")}>Credit</th></tr></thead>
            <tbody>
              {tb.data.accounts.filter((a) => parseFloat(a.debit) || parseFloat(a.credit)).map((a) => (
                <tr key={a.account_id} className="border-t border-[hsl(var(--border))]">
                  <td className={td}>{a.code}</td><td className={td}>{a.name}</td><td className={cn(td, "capitalize")}>{a.type}</td>
                  <td className={cn(td, num)}>{formatMoney(a.debit, base)}</td><td className={cn(td, num)}>{formatMoney(a.credit, base)}</td>
                </tr>
              ))}
              <tr className="border-t-2 border-[hsl(var(--border))] font-semibold">
                <td className={td} /><td className={td}>Total{tb.data.balanced ? "" : " (does not balance)"}</td><td className={td} />
                <td className={cn(td, num)}>{formatMoney(tb.data.total_debit, base)}</td><td className={cn(td, num)}>{formatMoney(tb.data.total_credit, base)}</td>
              </tr>
            </tbody>
          </table>
        </Card>
      ))}

      {tab === "ar" && (ar.isLoading || !ar.data ? <Skeleton className="h-48" /> : <AgingTable data={ar.data} />)}
      {tab === "ap" && (ap.isLoading || !ap.data ? <Skeleton className="h-48" /> : <AgingTable data={ap.data} />)}

      {tab === "gl" && !rangeBad && (!accountId ? (
        <EmptyState icon={BookOpen} title="Pick an account" description="Choose an account to see every line posted to it." />
      ) : gl.isLoading || !gl.data ? <Skeleton className="h-48" /> : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full">
            <thead><tr><th className={th}>Date</th><th className={th}>Entry</th><th className={th}>Details</th><th className={cn(th, "text-right")}>Debit</th><th className={cn(th, "text-right")}>Credit</th><th className={cn(th, "text-right")}>Balance</th></tr></thead>
            <tbody>
              <tr className="font-medium"><td className={td} colSpan={5}>Opening balance</td><td className={cn(td, num)}>{formatMoney(gl.data.opening_balance, gl.data.currency)}</td></tr>
              {gl.data.lines.map((l, i) => (
                <tr key={`${l.entry_id}-${i}`} className="border-t border-[hsl(var(--border))]">
                  <td className={td}>{l.date}</td><td className={td}>{l.number}</td><td className={td}>{l.memo || l.description || "—"}{l.reference ? ` · ${l.reference}` : ""}</td>
                  <td className={cn(td, num)}>{parseFloat(l.debit) ? formatMoney(l.debit, gl.data.currency) : ""}</td>
                  <td className={cn(td, num)}>{parseFloat(l.credit) ? formatMoney(l.credit, gl.data.currency) : ""}</td>
                  <td className={cn(td, num)}>{formatMoney(l.balance, gl.data.currency)}</td>
                </tr>
              ))}
              <tr className="border-t-2 border-[hsl(var(--border))] font-semibold">
                <td className={td} colSpan={3}>Closing balance</td>
                <td className={cn(td, num)}>{formatMoney(gl.data.total_debit, gl.data.currency)}</td><td className={cn(td, num)}>{formatMoney(gl.data.total_credit, gl.data.currency)}</td>
                <td className={cn(td, num)} data-testid="gl-closing">{formatMoney(gl.data.closing_balance, gl.data.currency)}</td>
              </tr>
            </tbody>
          </table>
          {gl.data.truncated && <p className="p-3 text-xs text-[hsl(var(--foreground-muted))]">Showing the first 5,000 lines. Narrow the dates to see the rest.</p>}
        </Card>
      ))}
    </div>
  );
}

"use client";

import { useMemo, useState } from "react";
import { Download, Percent } from "lucide-react";
import { Button, Card, EmptyState, PageHeader, Skeleton } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { cn } from "@/utils/cn";
import { formatMoney } from "@/services/finance.service";
import { PRESET_LABEL, presetRange, type Preset } from "@/services/finance-reports.service";
import { exportTaxReport, useTaxReport, type TaxSide } from "@/services/finance-taxes.service";
import { inp } from "../sales/CustomerDialog";

const th = "px-3 py-2 text-left text-xs font-semibold text-[hsl(var(--foreground-muted))]";
const td = "px-3 py-2 text-sm";
const PRESETS: Exclude<Preset, "custom">[] = ["this_month", "last_month", "this_quarter", "this_fy", "this_year", "last_year"];

function Side({ title, side, currency }: { title: string; side: TaxSide; currency: string }) {
  return (
    <Card className="overflow-x-auto p-0">
      <h2 className="px-4 pt-4 font-heading text-base font-semibold">{title}</h2>
      <table className="w-full" aria-label={title}>
        <thead><tr><th className={th}>Tax rate</th><th className={cn(th, "text-right")}>Documents</th><th className={cn(th, "text-right")}>Taxable amount</th><th className={cn(th, "text-right")}>Tax</th></tr></thead>
        <tbody>
          {side.rows.length === 0 && <tr><td colSpan={4} className={cn(td, "text-[hsl(var(--foreground-muted))]")}>Nothing in this period.</td></tr>}
          {side.rows.map((r) => (
            <tr key={`${r.tax_rate_id ?? "none"}-${r.percent}`} className="border-t border-[hsl(var(--border))]">
              <td className={td}>{r.name}{r.tax_rate_id && <span className="ml-2 text-xs text-[hsl(var(--foreground-muted))]">{r.percent}%</span>}</td>
              <td className={cn(td, "text-right tabular-nums")}>{r.documents}</td>
              <td className={cn(td, "text-right tabular-nums")}>{formatMoney(r.taxable, currency)}</td>
              <td className={cn(td, "text-right tabular-nums")}>{formatMoney(r.tax, currency)}</td>
            </tr>
          ))}
          <tr className="border-t border-[hsl(var(--border))] font-semibold">
            <td className={td}>Total</td><td className={td} />
            <td className={cn(td, "text-right tabular-nums")}>{formatMoney(side.taxable, currency)}</td>
            <td className={cn(td, "text-right tabular-nums")} data-testid={`${title}-tax`}>{formatMoney(side.tax, currency)}</td>
          </tr>
        </tbody>
      </table>
    </Card>
  );
}

export default function TaxesPage() {
  const canExport = useAuthStore((s) => s.hasPermission("finance.export"));
  const initial = useMemo(() => presetRange("this_month"), []);
  const [preset, setPreset] = useState<Preset>("this_month");
  const [from, setFrom] = useState(initial.from);
  const [to, setTo] = useState(initial.to);
  const bad = !!from && !!to && from > to;
  const report = useTaxReport(from, to, !bad && !!from && !!to);
  const cur = report.data?.currency ?? "PKR";

  const pick = (p: Preset) => { setPreset(p); if (p !== "custom") { const r = presetRange(p); setFrom(r.from); setTo(r.to); } };

  return (
    <div className="space-y-6">
      <PageHeader title="Taxes"
        action={canExport && (
          <div className="flex gap-2">
            <Button variant="outline" icon={<Download size={15} />} disabled={bad || !from || !to} onClick={() => void exportTaxReport("xlsx", from, to)}>Excel</Button>
            <Button variant="outline" icon={<Download size={15} />} disabled={bad || !from || !to} onClick={() => void exportTaxReport("csv", from, to)}>CSV</Button>
          </div>
        )} />

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button key={p} type="button" aria-pressed={preset === p} onClick={() => pick(p)}
              className={cn("rounded-full border px-3 py-1 text-xs", preset === p ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]" : "border-[hsl(var(--border))]")}>
              {PRESET_LABEL[p]}
            </button>
          ))}
        </div>
        <div><label htmlFor="tx-from" className="mb-1 block text-xs font-medium">From</label>
          <input id="tx-from" type="date" className={inp} value={from} onChange={(e) => { setFrom(e.target.value); setPreset("custom"); }} /></div>
        <div><label htmlFor="tx-to" className="mb-1 block text-xs font-medium">To</label>
          <input id="tx-to" type="date" className={inp} value={to} onChange={(e) => { setTo(e.target.value); setPreset("custom"); }} /></div>
      </div>
      {bad && <p role="alert" className="text-sm text-red-600">The start date is after the end date.</p>}

      {report.isLoading || (!report.data && !report.isError && !bad) ? <Skeleton className="h-48" /> : report.isError ? (
        <p role="alert" className="text-sm text-red-600">Could not load the tax report.</p>
      ) : report.data && (
        <>
          <Card className="flex flex-wrap items-center justify-between gap-3 p-5">
            <div>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">Net tax payable (sales tax minus purchase tax)</p>
              <p className="font-heading text-2xl font-semibold tabular-nums" data-testid="net-tax">{formatMoney(report.data.net_tax_payable, cur)}</p>
              {parseFloat(report.data.net_tax_payable) < 0 && <p className="text-xs text-[hsl(var(--foreground-muted))]">A negative amount means you can claim it back.</p>}
            </div>
            <p className="max-w-sm text-xs text-[hsl(var(--foreground-muted))]">Counts posted invoices and bills by issue date. Drafts and voided documents are left out.</p>
          </Card>
          {report.data.sales.rows.length === 0 && report.data.purchases.rows.length === 0 && (
            <EmptyState icon={Percent} title="No taxed documents in this period" description="Invoices and bills with a tax rate will show up here once they are sent or posted." />
          )}
          <div className="grid gap-6 lg:grid-cols-2">
            <Side title="Sales (tax you charged)" side={report.data.sales} currency={cur} />
            <Side title="Purchases (tax you paid)" side={report.data.purchases} currency={cur} />
          </div>
        </>
      )}
    </div>
  );
}

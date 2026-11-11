"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Skeleton, Tabs } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { formatMoney, useFinSummary } from "@/services/finance.service";
import {
  PERIOD_LABEL, SAVED_LABEL, shiftDate, today, useBudget, useSetOpening, useSetPlan,
  type BudgetPeriod, type BudgetSection,
} from "@/services/finance-budget.service";

const NAVY = "#243b5e";
const ORANGE = "#ff5a14";
const HILITE = "#fde6df";
const cell = "px-3 py-1.5 text-sm tabular-nums text-right";

function Bar({ planned, actual, label, currency }: { planned: string; actual: string; label: string; currency: string }) {
  const p = parseFloat(planned) || 0, a = parseFloat(actual) || 0;
  const pct = p > 0 ? Math.min(100, (a / p) * 100) : a > 0 ? 100 : 0;
  return (
    <div className="space-y-1" aria-label={`${label} summary`}>
      <div className="flex items-center gap-4 text-sm"><span className="w-14" style={{ color: NAVY }}>Planned</span><span className="tabular-nums" style={{ color: NAVY }}>{formatMoney(planned, currency)}</span></div>
      <div className="flex items-center gap-4 text-sm">
        <span className="w-14" style={{ color: NAVY }}>Actual</span><span className="w-24 tabular-nums" style={{ color: NAVY }}>{formatMoney(actual, currency)}</span>
        <div className="h-4 flex-1 rounded-sm bg-[#e3e8ef]"><div className="h-4 rounded-sm" style={{ width: `${pct}%`, background: NAVY }} /></div>
      </div>
    </div>
  );
}

function PlanTable({ kind, title, data, currency, canEdit, onPlan }: {
  kind: "income" | "expense"; title: string; data: BudgetSection; currency: string; canEdit: boolean; onPlan: (category: string, value: string) => void;
}) {
  return (
    <div className="min-w-0">
      <h2 className="mb-2 text-2xl font-bold" style={{ color: ORANGE }}>{title}</h2>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse" aria-label={`${title} table`}>
          <thead>
            <tr className="border-b border-[#cbd3df]">
              <th className="px-3 py-1.5 text-left text-xs font-normal italic" style={{ color: NAVY }} />
              {["Planned", "Actual", "Diff."].map((h) => <th key={h} className="px-3 py-1.5 text-right text-base font-semibold" style={{ color: NAVY }}>{h}</th>)}
            </tr>
            <tr className="border-b border-[#cbd3df]">
              <th className="px-3 py-1.5 text-left text-xs font-normal italic" style={{ color: NAVY }}>Totals</th>
              <td className="px-3 py-1.5 text-right text-xs italic tabular-nums" style={{ color: NAVY }}>{formatMoney(data.planned, currency)}</td>
              <td className="px-3 py-1.5 text-right text-xs italic tabular-nums" style={{ color: NAVY }}>{formatMoney(data.actual, currency)}</td>
              <td className="px-3 py-1.5 text-right text-xs italic tabular-nums" style={{ color: NAVY }}>{formatMoney(data.diff, currency)}</td>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.category} className="border-b border-[#e3e8ef]" style={{ color: NAVY }}>
                <th scope="row" className="px-3 py-1.5 text-left text-sm font-semibold" style={{ background: HILITE }}>{r.category}</th>
                <td className={cell} style={{ background: HILITE }}>
                  {canEdit ? (
                    <input key={`${kind}-${r.category}-${r.planned}`} type="number" min="0" step="0.01" aria-label={`Planned ${r.category}`}
                      defaultValue={parseFloat(r.planned) ? r.planned : ""} placeholder="0"
                      className="w-24 bg-transparent text-right outline-none focus:ring-1 focus:ring-[#ff5a14]"
                      onBlur={(e) => { const v = e.target.value.trim() || "0"; if (parseFloat(v) !== parseFloat(r.planned)) onPlan(r.category, v); }} />
                  ) : formatMoney(r.planned, currency)}
                </td>
                <td className={cell}>{formatMoney(r.actual, currency)}</td>
                <td className={cell} style={parseFloat(r.diff) < 0 ? { color: "#c62828" } : undefined}>{formatMoney(r.diff, currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function BudgetPage() {
  const canManage = useAuthStore((s) => s.hasPermission("finance.manage"));
  const [period, setPeriod] = useState<BudgetPeriod>("month");
  const [date, setDate] = useState(today());
  const q = useBudget(period, date);
  const summary = useFinSummary();
  const setPlan = useSetPlan();
  const setOpening = useSetOpening();
  const currency = summary.data?.currency ?? "PKR";
  const b = q.data;

  const startN = b ? parseFloat(b.starting_balance) : 0, endN = b ? parseFloat(b.end_balance) : 0;
  const top = Math.max(Math.abs(startN), Math.abs(endN), 1);
  const h = (v: number) => `${Math.max(4, (Math.abs(v) / top) * 100)}%`;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs<BudgetPeriod> active={period} onChange={(p) => { setPeriod(p); setDate(today()); }}
          tabs={(Object.keys(PERIOD_LABEL) as BudgetPeriod[]).map((p) => ({ value: p, label: PERIOD_LABEL[p] }))} />
        <div className="flex items-center gap-2">
          <button type="button" aria-label={`Previous ${period}`} className="rounded-md border p-1.5" onClick={() => setDate(shiftDate(period, date, -1))}><ChevronLeft size={16} /></button>
          <button type="button" aria-label={`Next ${period}`} className="rounded-md border p-1.5" onClick={() => setDate(shiftDate(period, date, 1))}><ChevronRight size={16} /></button>
        </div>
      </div>

      <div className="grid gap-6 rounded-md p-6 text-white md:grid-cols-2" style={{ background: NAVY }}>
        <div>
          <p className="mb-2 text-sm font-bold uppercase tracking-wide">Get started</p>
          <p className="text-sm leading-relaxed">Set your starting balance, then customize your planned spending amounts in the &lsquo;Income&rsquo; and &lsquo;Expenses&rsquo; tables below. As you enter data in the &lsquo;Transactions&rsquo; tab, this page will automatically update to show a summary of your spending for the {SAVED_LABEL[period]}.</p>
        </div>
        <div>
          <p className="mb-2 text-sm font-bold uppercase tracking-wide">Note</p>
          <p className="rounded-sm px-2 py-1 text-sm italic" style={{ background: HILITE, color: NAVY }}>Only edit highlighted cells.</p>
        </div>
      </div>

      {q.isLoading || !b ? <Skeleton className="h-96" /> : (
        <>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <h1 className="text-4xl font-bold" style={{ color: ORANGE }}>Budget {b.label}</h1>
            <label className="flex items-center gap-2 text-sm font-bold" style={{ color: NAVY }}>
              Starting balance:
              {canManage ? (
                <input key={`${b.start}-${b.starting_balance}-${b.starting_balance_manual}`} type="number" step="0.01" aria-label="Starting balance"
                  defaultValue={b.starting_balance} className="w-32 rounded-sm px-2 py-1 text-right font-normal tabular-nums outline-none" style={{ background: HILITE }}
                  onBlur={(e) => {
                    const v = e.target.value.trim();
                    if (v === "" ? b.starting_balance_manual : parseFloat(v) !== parseFloat(b.starting_balance)) setOpening.mutate({ period, date, starting_balance: v === "" ? null : v });
                  }} />
              ) : <span className="rounded-sm px-2 py-1 font-normal tabular-nums" style={{ background: HILITE }}>{formatMoney(b.starting_balance, currency)}</span>}
            </label>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <div className="flex items-end justify-center gap-6" aria-label="Start and end balance" style={{ minHeight: 220 }}>
              <div className="flex h-44 w-24 flex-col items-center justify-end"><div className="w-1 border-l border-dashed border-[#9aa6b8]" style={{ height: h(startN) }} /></div>
              <div className="flex h-44 w-16 flex-col items-center justify-end"><div className="w-full" data-testid="end-bar" style={{ height: h(endN), background: ORANGE }} /></div>
            </div>
            <div className="flex flex-col items-center justify-center rounded-md bg-[#e9ecf1] p-6 text-center" style={{ color: NAVY }}>
              <p className="border-b border-dashed border-[#9aa6b8] pb-3 text-sm italic">Increase in total savings</p>
              <p className="py-3 text-4xl font-semibold" data-testid="saved">{formatMoney(b.saved, currency)}</p>
              <p className="text-sm italic">Saved this {SAVED_LABEL[period]}</p>
            </div>
          </div>
          <div className="flex justify-center gap-10 text-center" style={{ marginTop: -16 }}>
            <div><p className="text-lg font-bold" style={{ color: NAVY }}>START BALANCE</p><p className="text-xs italic" style={{ color: NAVY }} data-testid="start-balance">{formatMoney(b.starting_balance, currency)}</p></div>
            <div><p className="text-lg font-bold" style={{ color: ORANGE }}>END BALANCE</p><p className="text-xs italic" style={{ color: ORANGE }} data-testid="end-balance">{formatMoney(b.end_balance, currency)}</p></div>
          </div>

          <div className="grid gap-8 md:grid-cols-2">
            <div><h2 className="mb-2 text-xl font-bold" style={{ color: NAVY }}>Expenses</h2><Bar planned={b.expenses.planned} actual={b.expenses.actual} label="Expenses" currency={currency} /></div>
            <div><h2 className="mb-2 text-xl font-bold" style={{ color: NAVY }}>Income</h2><Bar planned={b.income.planned} actual={b.income.actual} label="Income" currency={currency} /></div>
          </div>

          <div className="grid gap-8 lg:grid-cols-2">
            <PlanTable kind="expense" title="Expenses" data={b.expenses} currency={currency} canEdit={canManage}
              onPlan={(category, planned) => setPlan.mutate({ period, date, kind: "expense", category, planned })} />
            <PlanTable kind="income" title="Income" data={b.income} currency={currency} canEdit={canManage}
              onPlan={(category, planned) => setPlan.mutate({ period, date, kind: "income", category, planned })} />
          </div>
        </>
      )}
    </div>
  );
}

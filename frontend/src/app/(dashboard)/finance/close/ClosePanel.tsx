"use client";

import { useEffect, useState } from "react";
import { Button, Card, Skeleton } from "@/components/atoms";
import { formatMoney } from "@/services/finance.service";
import {
  useClosePeriod, useClosePreview, useCloseStatus, useReopenPeriod, type CloseKind,
} from "@/services/finance-close.service";
import { today } from "@/services/finance-budget.service";
import { Modal, inp } from "../sales/CustomerDialog";

export function ClosePanel({ currency, canManage }: { currency: string; canManage: boolean }) {
  const status = useCloseStatus();
  const [kind, setKind] = useState<CloseKind>("month");
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState<"close" | "reopen" | null>(null);
  const preview = useClosePreview(kind, date);
  const close = useClosePeriod();
  const reopen = useReopenPeriod();

  // Start on the period the server suggests (the next one that has ended), else today.
  const suggested = status.data?.suggested?.period_end;
  useEffect(() => { if (!date && status.data) setDate(suggested ?? today()); }, [date, status.data, suggested]);

  const locked = status.data?.locked_through ?? null;
  const p = preview.data;
  const latest = status.data?.closes[0];
  const row = (label: string, value: string) => (
    <div className="flex justify-between py-1 text-sm"><span>{label}</span><span className="tabular-nums">{formatMoney(value, currency)}</span></div>
  );

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-6">
        <Card className="p-5">
          <p className="text-xs text-[hsl(var(--foreground-muted))]">Books are</p>
          {status.isLoading ? <Skeleton className="mt-2 h-6" /> : (
            <p className="font-heading text-lg font-semibold" data-testid="lock-state">
              {locked ? `Closed through ${locked}` : "Open — nothing is closed yet"}
            </p>
          )}
          <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">
            Nothing can be posted, edited or voided on or before the closed date. Invoices, bills, payments, bank bookings and recurring runs all follow this.
          </p>
        </Card>

        <Card className="space-y-4 p-5">
          <h2 className="font-heading text-base font-semibold">Close a period</h2>
          <div className="grid grid-cols-2 gap-3">
            <div><label htmlFor="cl-kind" className="mb-1 block text-xs font-medium">Close a</label>
              <select id="cl-kind" className={inp} value={kind} onChange={(e) => setKind(e.target.value as CloseKind)}>
                <option value="month">Month</option><option value="year">Financial year (Jul–Jun)</option>
              </select></div>
            <div><label htmlFor="cl-date" className="mb-1 block text-xs font-medium">Any date in it</label>
              <input id="cl-date" type="date" className={inp} value={date} onChange={(e) => setDate(e.target.value)} /></div>
          </div>

          {preview.isLoading || (!p && !preview.isError && !!date) ? <Skeleton className="h-28" /> : p && (
            <div className="rounded-lg bg-[hsl(var(--secondary))] p-4">
              <p className="mb-1 text-sm font-medium">{p.label} <span className="text-xs font-normal text-[hsl(var(--foreground-muted))]">({p.period_start} to {p.period_end})</span></p>
              {row("Income", p.income)}
              {row("Expenses", p.expenses)}
              <div className="border-t border-[hsl(var(--border))] pt-1">{row("Net profit", p.net_profit)}</div>
              {p.blockers.map((b) => <p key={b} role="alert" className="mt-2 text-sm text-red-600">{b}</p>)}
              {p.warnings.map((w) => <p key={w} className="mt-2 text-xs text-amber-600">{w}</p>)}
              {p.can_close && p.warnings.length === 0 && <p className="mt-2 text-sm text-green-700">Everything looks clean.</p>}
            </div>
          )}

          {canManage && (
            <>
              <div><label htmlFor="cl-note" className="mb-1 block text-xs font-medium">Note (optional)</label>
                <input id="cl-note" className={inp} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></div>
              <Button size="sm" disabled={!p?.can_close || close.isPending} onClick={() => setConfirm("close")}>Close period</Button>
            </>
          )}
        </Card>
      </div>

      <Card className="p-5">
        <h2 className="mb-3 font-heading text-base font-semibold">Closed periods</h2>
        {status.isLoading ? <Skeleton className="h-20" /> : !status.data?.closes.length ? (
          <p className="text-sm text-[hsl(var(--foreground-muted))]">None yet.</p>
        ) : (
          <ul className="divide-y divide-[hsl(var(--border))]">
            {status.data.closes.map((c, i) => (
              <li key={c.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <div>
                  <p className="font-medium">{c.period_start} to {c.period_end} <span className="text-xs font-normal text-[hsl(var(--foreground-muted))]">{c.period_type === "year" ? "financial year" : "month"}</span></p>
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">Net profit {formatMoney(c.net_profit, currency)}{c.note ? ` · ${c.note}` : ""}</p>
                </div>
                {canManage && i === 0 && <Button variant="outline" size="sm" disabled={reopen.isPending} onClick={() => setConfirm("reopen")}>Reopen</Button>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {confirm === "close" && p && (
        <Modal title="Close this period?" onClose={() => setConfirm(null)} footer={<>
          <Button variant="outline" size="sm" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button size="sm" disabled={close.isPending}
            onClick={() => close.mutate({ period_type: kind, date, ...(note.trim() ? { note: note.trim() } : {}) }, { onSuccess: () => { setConfirm(null); setNote(""); setDate(""); } })}>
            {close.isPending ? "Closing…" : "Close period"}
          </Button>
        </>}>
          <p className="text-sm">Everything dated up to <strong>{p.period_end}</strong> will be locked. You can reopen the latest closed period later if you need to fix something.</p>
          {p.warnings.length > 0 && <p className="text-xs text-amber-600">{p.warnings.length} warning(s) above are still open.</p>}
        </Modal>
      )}
      {confirm === "reopen" && latest && (
        <Modal title="Reopen this period?" onClose={() => setConfirm(null)} footer={<>
          <Button variant="outline" size="sm" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button size="sm" disabled={reopen.isPending} onClick={() => reopen.mutate(undefined, { onSuccess: () => { setConfirm(null); setDate(""); } })}>
            {reopen.isPending ? "Reopening…" : "Reopen"}
          </Button>
        </>}>
          <p className="text-sm">Entries dated {latest.period_start} to {latest.period_end} can be posted and changed again until you close it once more.</p>
        </Modal>
      )}
    </div>
  );
}

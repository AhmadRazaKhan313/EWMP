"use client";

import { useState } from "react";
import { FilePlus2, RefreshCw, Trash2, XCircle } from "lucide-react";
import { Badge, Button, Card, Skeleton } from "@/components/atoms";
import {
  CONTRACT_TYPES, useContractActions, useEmployeeContracts,
  type Contract, type ContractInput, type ContractState,
} from "@/services/employeeLifecycle.service";

const field =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--brand-300))]";

export const STATE_BADGE: Record<ContractState, { label: string; variant: "success" | "warning" | "error" | "default" | "info" }> = {
  active: { label: "Active", variant: "success" },
  expiring: { label: "Expiring soon", variant: "warning" },
  expired: { label: "Expired", variant: "error" },
  renewed: { label: "Renewed", variant: "default" },
  terminated: { label: "Terminated", variant: "default" },
};

export const typeLabel = (v: string) => CONTRACT_TYPES.find((t) => t.value === v)?.label ?? v;
const fmt = (d: string | null) =>
  d ? new Date(d).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" }) : "No end date";

export function ContractStateBadge({ contract }: { contract: Contract }) {
  const s = STATE_BADGE[contract.state] ?? STATE_BADGE.active;
  return (
    <Badge variant={s.variant}>
      {s.label}
      {contract.state === "expiring" && contract.days_left !== null ? ` · ${contract.days_left}d` : ""}
    </Badge>
  );
}

type Mode = { kind: "add" } | { kind: "edit"; contract: Contract } | { kind: "renew"; contract: Contract };

function ContractForm({
  mode, busy, onCancel, onSubmit,
}: { mode: Mode; busy: boolean; onCancel: () => void; onSubmit: (v: ContractInput) => void }) {
  const base = mode.kind === "add" ? null : mode.contract;
  const nextStart = (() => {
    if (mode.kind !== "renew" || !base?.end_date) return "";
    const d = new Date(base.end_date);
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  })();
  const [type, setType] = useState(base?.contract_type ?? "fixed_term");
  const [start, setStart] = useState(mode.kind === "renew" ? nextStart : base?.start_date ?? "");
  const [end, setEnd] = useState(mode.kind === "renew" ? "" : base?.end_date ?? "");
  const [alertDays, setAlertDays] = useState(String(base?.renewal_alert_days ?? 30));
  const [notes, setNotes] = useState(mode.kind === "renew" ? "" : base?.notes ?? "");

  const permanent = type === "permanent";
  const valid = !!start && (permanent || (!!end && end > start)) && Number(alertDays) >= 1 && Number(alertDays) <= 365;
  const title = { add: "Add contract", edit: "Edit contract", renew: "Renew contract" }[mode.kind];

  return (
    <div className="space-y-3 rounded-lg border border-[hsl(var(--border))] p-4" data-testid="contract-form">
      <p className="text-sm font-semibold">{title}</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-xs font-medium" htmlFor="c-type">Contract type</label>
          <select id="c-type" className={field} value={type} onChange={(e) => setType(e.target.value)}>
            {CONTRACT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium" htmlFor="c-alert">Remind HR (days before end)</label>
          <input id="c-alert" type="number" min={1} max={365} className={field} value={alertDays} onChange={(e) => setAlertDays(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium" htmlFor="c-start">Start date</label>
          <input id="c-start" type="date" className={field} value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        {!permanent && (
          <div>
            <label className="mb-1 block text-xs font-medium" htmlFor="c-end">End date</label>
            <input id="c-end" type="date" className={field} value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} />
          </div>
        )}
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium" htmlFor="c-notes">Notes (optional)</label>
        <textarea id="c-notes" rows={2} className={field} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onCancel}>Cancel</Button>
        <Button
          disabled={!valid || busy}
          onClick={() =>
            onSubmit({
              contract_type: type, start_date: start, end_date: permanent ? null : end,
              renewal_alert_days: Number(alertDays), notes: notes.trim() || null,
            })
          }
        >
          {busy ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}

/** Contract tab on the employee profile: history, add / edit / renew / terminate. */
export function ContractsPanel({ employeeId, canManage }: { employeeId: string; canManage: boolean }) {
  const { data, isLoading } = useEmployeeContracts(employeeId);
  const actions = useContractActions(employeeId);
  const [mode, setMode] = useState<Mode | null>(null);
  const [terminating, setTerminating] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const items = data?.items ?? [];
  const hasActive = items.some((c) => c.status === "active");
  const busy = actions.create.isPending || actions.update.isPending || actions.renew.isPending;
  const close = () => setMode(null);

  function submit(v: ContractInput) {
    if (!mode) return;
    const opts = { onSuccess: close };
    if (mode.kind === "add") actions.create.mutate(v, opts);
    else if (mode.kind === "edit") actions.update.mutate({ id: mode.contract.id, data: v }, opts);
    else actions.renew.mutate({ id: mode.contract.id, data: { ...v, start_date: v.start_date } }, opts);
  }

  return (
    <div className="space-y-4" data-testid="tab-contract">
      <Card padding={false}>
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
          <h3 className="font-heading text-sm font-semibold">Contracts</h3>
          {canManage && !hasActive && !mode && (
            <Button size="sm" icon={<FilePlus2 size={13} />} onClick={() => setMode({ kind: "add" })}>Add contract</Button>
          )}
        </div>
        <div className="space-y-3 px-5 py-4">
          {mode && <ContractForm mode={mode} busy={busy} onCancel={close} onSubmit={submit} />}
          {isLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : items.length === 0 ? (
            <p className="text-sm text-[hsl(var(--foreground-muted))]">No contract on file yet.</p>
          ) : (
            items.map((c) => (
              <div key={c.id} className="rounded-lg border border-[hsl(var(--border))] p-3" data-testid={`contract-${c.id}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium">
                    {typeLabel(c.contract_type)}
                    <span className="ml-2 font-normal text-[hsl(var(--foreground-muted))]">
                      {fmt(c.start_date)} → {fmt(c.end_date)}
                    </span>
                  </p>
                  <ContractStateBadge contract={c} />
                </div>
                {c.notes && <p className="mt-1 whitespace-pre-line text-xs text-[hsl(var(--foreground-subtle))]">{c.notes}</p>}
                {canManage && c.status === "active" && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" icon={<RefreshCw size={12} />} onClick={() => setMode({ kind: "renew", contract: c })}>Renew</Button>
                    <Button size="sm" variant="outline" onClick={() => setMode({ kind: "edit", contract: c })}>Edit</Button>
                    <Button size="sm" variant="outline" icon={<XCircle size={12} />} onClick={() => { setTerminating(c.id); setReason(""); }}>Terminate</Button>
                  </div>
                )}
                {canManage && c.status !== "active" && (
                  <div className="mt-2">
                    <Button size="sm" variant="outline" icon={<Trash2 size={12} />} onClick={() => actions.remove.mutate(c.id)}>Delete</Button>
                  </div>
                )}
                {terminating === c.id && (
                  <div className="mt-3 space-y-2 rounded-md bg-[hsl(var(--background-subtle))] p-3">
                    <label className="block text-xs font-medium" htmlFor={`t-${c.id}`}>Reason (optional)</label>
                    <input id={`t-${c.id}`} className={field} value={reason} onChange={(e) => setReason(e.target.value)} />
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => setTerminating(null)}>Cancel</Button>
                      <Button
                        size="sm"
                        disabled={actions.terminate.isPending}
                        onClick={() => actions.terminate.mutate({ id: c.id, reason }, { onSuccess: () => setTerminating(null) })}
                      >
                        Confirm terminate
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}

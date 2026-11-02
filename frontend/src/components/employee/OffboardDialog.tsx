"use client";

import { useState } from "react";
import { UserX, X } from "lucide-react";
import { Button } from "@/components/atoms";
import { OFFBOARD_REASONS, useOffboardEmployee, type OffboardReason } from "@/services/employeeLifecycle.service";

const field =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--brand-300))]";

/**
 * Real offboarding flow (replaces the old no-op button). Resignation sets the
 * status to Resigned, every other reason to Terminated; the server disables the
 * login, ends the active contract and writes a status-history row.
 */
export function OffboardDialog({
  employeeId, employeeName, open, onClose,
}: { employeeId: string; employeeName: string; open: boolean; onClose: () => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [reasonType, setReasonType] = useState<OffboardReason>("resignation");
  const [date, setDate] = useState(today);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const offboard = useOffboardEmployee(employeeId);

  if (!open) return null;
  const ready = reason.trim().length > 0 && !!date && confirmed && !offboard.isPending;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div
        role="dialog"
        aria-label="Offboard employee"
        className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl bg-[hsl(var(--background))] shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
          <h3 className="flex items-center gap-2 font-heading text-sm font-semibold">
            <UserX size={15} /> Offboard {employeeName}
          </h3>
          <button aria-label="Close" onClick={onClose} className="rounded p-1 hover:bg-[hsl(var(--accent))]">
            <X size={15} />
          </button>
        </div>
        <div className="space-y-3 px-5 py-4">
          <div>
            <label className="mb-1 block text-xs font-medium" htmlFor="off-type">Reason for leaving</label>
            <select id="off-type" className={field} value={reasonType} onChange={(e) => setReasonType(e.target.value as OffboardReason)}>
              {OFFBOARD_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium" htmlFor="off-date">Last working day</label>
            <input id="off-date" type="date" className={field} value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium" htmlFor="off-reason">Details (required)</label>
            <textarea id="off-reason" rows={3} className={field} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Short note for the record" />
          </div>
          <p className="rounded-md bg-[hsl(var(--warning-subtle))] px-3 py-2 text-xs">
            Their login will be turned off immediately and their active contract will end. This is recorded in the
            status history.
          </p>
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            I understand and want to offboard {employeeName}
          </label>
        </div>
        <div className="flex justify-end gap-2 border-t border-[hsl(var(--border))] px-5 py-3">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            disabled={!ready}
            onClick={() =>
              offboard.mutate(
                { date_of_leaving: date, exit_reason: reason.trim(), reason_type: reasonType },
                { onSuccess: onClose },
              )
            }
          >
            {offboard.isPending ? "Offboarding…" : "Offboard"}
          </Button>
        </div>
      </div>
    </>
  );
}

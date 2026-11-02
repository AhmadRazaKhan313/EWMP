"use client";

import { useState } from "react";
import { AlertTriangle, Loader2, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import apiClient from "@/services/api-client";
import { Button } from "@/components/atoms";

/**
 * Admin attendance correction (T-01 / T-02 / T-03).
 *
 *  - A day that already has a record: change check-in / check-out / status /
 *    notes, or delete the day. No approval step; a written reason is required
 *    and the server writes an audit-log row.
 *  - A day with no record: mark the employee Present / Absent / On leave /
 *    WFH / Half day on their behalf.
 *  - If the payroll for that date is locked the server answers 409
 *    PAYROLL_LOCKED; we show the warning, and only the owner gets an
 *    "Override" button.
 *
 * Times are office-clock times (the organisation's timezone), so the time
 * boxes start empty ("leave blank to keep") instead of guessing from the
 * browser's timezone.
 */

export interface CorrectionRow {
  employee_id: string;
  employee_name: string;
  employee_code: string;
  record_id: string | null;
  status: string;
  check_in: string | null;
  check_out: string | null;
}

export const STATUS_OPTIONS = [
  { value: "present", label: "Present" },
  { value: "absent", label: "Absent" },
  { value: "on_leave", label: "On leave" },
  { value: "work_from_home", label: "Work from home" },
  { value: "half_day", label: "Half day" },
];

const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

export interface CorrectionValues {
  status: string;
  checkIn: string;
  checkOut: string;
  notes: string;
  reason: string;
}

/** What is wrong with the form, or null. Pure, so it is easy to test. */
export function correctionProblem(isNew: boolean, v: CorrectionValues): string | null {
  if (v.reason.trim().length < 3) return "Please write a reason (at least 3 characters).";
  if (v.checkIn && !TIME.test(v.checkIn)) return "Check-in must be a time like 09:00.";
  if (v.checkOut && !TIME.test(v.checkOut)) return "Check-out must be a time like 17:30.";
  if (isNew) {
    if (!v.status) return "Choose what to mark this day as.";
    if (v.status === "present" && !(v.checkIn && v.checkOut)) {
      return "To mark someone present, give both check-in and check-out.";
    }
    if (v.checkOut && !v.checkIn) return "Give the check-in time too.";
  } else if (!v.status && !v.checkIn && !v.checkOut && !v.notes.trim()) {
    return "Change at least one thing.";
  }
  return null;
}

interface ApiError {
  response?: { status?: number; data?: { error?: string; message?: string; detail?: { can_override?: boolean } | string } };
}

export function parseCorrectionError(err: unknown): { message: string; locked: boolean; canOverride: boolean } {
  const data = (err as ApiError)?.response?.data;
  const locked = data?.error === "PAYROLL_LOCKED";
  const canOverride = locked && typeof data?.detail === "object" && !!data.detail?.can_override;
  const detail = typeof data?.detail === "string" ? data.detail : undefined;
  return { message: data?.message || detail || "Couldn't save the change", locked, canOverride };
}

const field =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none " +
  "focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]";

export function AttendanceCorrectionDialog({
  row, date, onClose,
}: {
  row: CorrectionRow;
  /** YYYY-MM-DD of the day being corrected. */
  date: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const isNew = !row.record_id;
  const [values, setValues] = useState<CorrectionValues>({ status: "", checkIn: "", checkOut: "", notes: "", reason: "" });
  const [problem, setProblem] = useState<string | null>(null);
  const [lock, setLock] = useState<{ message: string; canOverride: boolean } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const set = (k: keyof CorrectionValues) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setValues((v) => ({ ...v, [k]: e.target.value }));

  const done = (msg: string) => {
    toast.success(msg);
    for (const key of ["attendance-daily", "attendance", "dashboard"]) void qc.invalidateQueries({ queryKey: [key] });
    onClose();
  };
  const failed = (err: unknown) => {
    const e = parseCorrectionError(err);
    if (e.locked) setLock({ message: e.message, canOverride: e.canOverride });
    else toast.error(e.message);
  };

  const save = useMutation({
    mutationFn: async (override: boolean) => {
      if (isNew) {
        return apiClient.post("/attendance", null, {
          params: {
            employee_id: row.employee_id, date, attendance_status: values.status, reason: values.reason.trim(),
            ...(values.checkIn ? { check_in: values.checkIn } : {}),
            ...(values.checkOut ? { check_out: values.checkOut } : {}),
          },
        });
      }
      return apiClient.patch(`/attendance/${row.record_id}`, {
        reason: values.reason.trim(),
        ...(values.checkIn ? { check_in: values.checkIn } : {}),
        ...(values.checkOut ? { check_out: values.checkOut } : {}),
        ...(values.status ? { status: values.status } : {}),
        ...(values.notes.trim() ? { notes: values.notes.trim() } : {}),
        ...(override ? { override_payroll_lock: true } : {}),
      });
    },
    onSuccess: () => done(isNew ? "Attendance marked" : "Attendance updated"),
    onError: failed,
  });

  const remove = useMutation({
    mutationFn: async (override: boolean) =>
      apiClient.delete(`/attendance/${row.record_id}`, {
        params: { reason: values.reason.trim(), ...(override ? { override_payroll_lock: true } : {}) },
      }),
    onSuccess: () => done("Day deleted"),
    onError: failed,
  });

  const busy = save.isPending || remove.isPending;
  const submit = (override = false) => {
    const p = correctionProblem(isNew, values);
    setProblem(p);
    if (!p) save.mutate(override);
  };
  const submitDelete = (override = false) => {
    const p = values.reason.trim().length < 3 ? "Please write a reason (at least 3 characters)." : null;
    setProblem(p);
    if (!p) remove.mutate(override);
  };
  const retryWithOverride = () => (confirmDelete ? submitDelete(true) : submit(true));

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div
        role="dialog"
        aria-label={isNew ? "Mark attendance" : "Correct attendance"}
        className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-xl bg-[hsl(var(--background))] shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div>
            <h2 className="font-heading text-lg font-semibold">{isNew ? "Mark attendance" : "Correct attendance"}</h2>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">
              {row.employee_name} · {row.employee_code} · {date}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close"
            className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))]">
            <X size={16} />
          </button>
        </div>

        <div className="max-h-[70vh] space-y-4 overflow-y-auto px-6 py-5">
          {!isNew && (
            <p className="rounded-md bg-[hsl(var(--muted))] px-3 py-2 text-xs text-[hsl(var(--foreground-subtle))]">
              Currently {row.status.replace(/_/g, " ")}
              {row.check_in ? `, in ${new Date(row.check_in).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}` : ""}
              {row.check_out ? `, out ${new Date(row.check_out).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}` : ""}.
              Leave a box blank to keep it as it is.
            </p>
          )}

          <div>
            <label htmlFor="corr-status" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">
              {isNew ? "Mark as" : "Status"}
            </label>
            <select id="corr-status" className={field} value={values.status} onChange={set("status")}>
              <option value="">{isNew ? "Select…" : "Keep as is"}</option>
              {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="corr-in" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">Check-in (office time)</label>
              <input id="corr-in" type="time" className={field} value={values.checkIn} onChange={set("checkIn")} />
            </div>
            <div>
              <label htmlFor="corr-out" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">Check-out (office time)</label>
              <input id="corr-out" type="time" className={field} value={values.checkOut} onChange={set("checkOut")} />
            </div>
          </div>

          {!isNew && (
            <div>
              <label htmlFor="corr-notes" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">Note (optional)</label>
              <input id="corr-notes" className={field} value={values.notes} onChange={set("notes")} />
            </div>
          )}

          <div>
            <label htmlFor="corr-reason" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">
              Reason <span className="text-[hsl(var(--destructive))]">*</span>
            </label>
            <textarea id="corr-reason" rows={2} className={field} value={values.reason} onChange={set("reason")}
              placeholder="Why is this being changed? It is kept in the audit log." />
          </div>

          {problem && <p role="alert" className="text-xs text-[hsl(var(--destructive))]">{problem}</p>}

          {lock && (
            <div role="alert" className="flex gap-2 rounded-md border border-[hsl(var(--warning))] bg-[hsl(var(--warning)/0.1)] p-3 text-sm">
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-[hsl(var(--warning))]" />
              <div className="space-y-2">
                <p>{lock.message}</p>
                {lock.canOverride && (
                  <Button size="sm" variant="outline" onClick={retryWithOverride} disabled={busy}>
                    Override the lock and continue
                  </Button>
                )}
              </div>
            </div>
          )}

          {confirmDelete && (
            <p className="text-sm text-[hsl(var(--destructive))]">
              This removes the whole day from attendance and payroll hours. It stays in the audit log.
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-[hsl(var(--border))] px-6 py-4">
          <div>
            {!isNew && !confirmDelete && (
              <Button variant="ghost" onClick={() => setConfirmDelete(true)} disabled={busy}>
                <Trash2 size={14} className="mr-1.5" /> Delete day
              </Button>
            )}
            {!isNew && confirmDelete && (
              <Button variant="destructive" onClick={() => submitDelete()} disabled={busy}>
                {remove.isPending && <Loader2 size={14} className="mr-1.5 animate-spin" />} Confirm delete
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={confirmDelete ? () => setConfirmDelete(false) : onClose} disabled={busy}>
              {confirmDelete ? "Back" : "Cancel"}
            </Button>
            {!confirmDelete && (
              <Button onClick={() => submit()} disabled={busy}>
                {save.isPending && <Loader2 size={14} className="mr-1.5 animate-spin" />}
                {isNew ? "Mark" : "Save"}
              </Button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

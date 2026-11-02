"use client";
import type { ReactNode } from "react";
import type { OfferStatus, TaskStatus } from "@/services/onboarding.service";
import { Badge } from "@/components/atoms";

type Variant = "success" | "warning" | "error" | "default" | "info";

export const inputCls =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none " +
  "focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))] disabled:opacity-60";

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground-subtle))]">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-[hsl(var(--foreground-muted))]">{hint}</span>}
    </label>
  );
}

export const OFFER_STATUS: Record<OfferStatus, { label: string; variant: Variant }> = {
  draft: { label: "Draft", variant: "default" },
  pending_approval: { label: "Awaiting approval", variant: "warning" },
  approved: { label: "Approved", variant: "info" },
  sent: { label: "Sent", variant: "info" },
  viewed: { label: "Viewed", variant: "info" },
  accepted: { label: "Accepted", variant: "success" },
  declined: { label: "Declined", variant: "error" },
  expired: { label: "Expired", variant: "error" },
  revoked: { label: "Withdrawn", variant: "error" },
  revised: { label: "Replaced", variant: "default" },
};

export function OfferStatusBadge({ status }: { status: OfferStatus }) {
  const c = OFFER_STATUS[status] ?? { label: status, variant: "default" as Variant };
  return <Badge variant={c.variant}>{c.label}</Badge>;
}

export const TASK_STATUS: Record<TaskStatus, { label: string; variant: Variant }> = {
  pending: { label: "To do", variant: "default" },
  in_progress: { label: "In progress", variant: "info" },
  done: { label: "Done", variant: "success" },
  skipped: { label: "Skipped", variant: "warning" },
};

export function ProgressBar({ percent }: { percent: number }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-[hsl(var(--secondary))]" role="progressbar"
         aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-[hsl(var(--primary))]" style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
    </div>
  );
}

export function fmtDate(v: string | null | undefined): string {
  if (!v) return "—";
  return new Date(v).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-heading text-lg font-semibold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

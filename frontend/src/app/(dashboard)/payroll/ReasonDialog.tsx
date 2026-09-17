"use client";

import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { Button } from "@/components/atoms";

export function ReasonDialog({
  title, description, confirmLabel, destructive, isPending, onConfirm, onClose,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  isPending: boolean;
  onConfirm: (reason: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-6 shadow-2xl">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="font-heading text-base font-semibold">{title}</h2>
            <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">{description}</p>
          </div>
          <button onClick={onClose} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))]">
            <X size={14} />
          </button>
        </div>

        <label className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">
          Reason <span className="text-[hsl(var(--destructive))]">*</span>
        </label>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder="Explain why — this is recorded in the audit log"
          className="w-full resize-none rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1"
        />

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            variant={destructive ? "destructive" : "primary"}
            disabled={!reason.trim() || isPending}
            onClick={() => onConfirm(reason)}
            icon={isPending ? <Loader2 size={14} className="animate-spin" /> : undefined}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </>
  );
}

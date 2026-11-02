"use client";

import { X, History } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "@/services/api-client";

interface AuditEntry {
  id: string;
  user_id: string;
  action: string;
  previous_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  reason: string | null;
  created_at: string;
}

const actionLabel: Record<string, string> = {
  RUN_APPROVED: "Approval recorded",
  RUN_REJECTED: "Rejected",
  RUN_FINALIZED: "Finalized & locked",
  RUN_REOPENED: "Reopened",
  RUN_REVERSED: "Reversed",
};

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-US", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function AuditLogDrawer({ runId, onClose }: { runId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["payroll-run-audit-log", runId],
    queryFn: async () => (await apiClient.get<{ items: AuditEntry[]; total: number }>(`/payroll/runs/${runId}/audit-log`)).data,
  });

  const entries = data?.items ?? [];

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col bg-[hsl(var(--background))] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div className="flex items-center gap-2">
            <History size={16} className="text-[hsl(var(--foreground-muted))]" />
            <h2 className="font-heading text-lg font-semibold">Audit Log</h2>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {isLoading ? (
            <p className="text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>
          ) : entries.length === 0 ? (
            <p className="text-sm text-[hsl(var(--foreground-muted))]">No approval, finalization, reopen, or reversal actions recorded yet for this run.</p>
          ) : (
            <div className="space-y-4">
              {entries.map((e, i) => (
                <div key={e.id} className="relative pl-6">
                  {i !== entries.length - 1 && (
                    <div className="absolute left-[5px] top-4 h-full w-px bg-[hsl(var(--border))]" />
                  )}
                  <div className="absolute left-0 top-1 h-2.5 w-2.5 rounded-full bg-[hsl(var(--primary))]" />
                  <p className="text-sm font-medium">{actionLabel[e.action] ?? e.action}</p>
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">{formatDateTime(e.created_at)}</p>
                  {e.reason && (
                    <p className="mt-1 rounded-md bg-[hsl(var(--accent))] px-2.5 py-1.5 text-xs text-[hsl(var(--foreground-subtle))]">
                      &ldquo;{e.reason}&rdquo;
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

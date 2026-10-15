"use client";

import { X, AlertTriangle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "@/services/api-client";

interface JournalEntry {
  purpose: string;
  account_code: string;
  account_name: string;
  debit: string;
  credit: string;
}

interface JournalEntriesData {
  run_name: string;
  entries: JournalEntry[];
  total_debits: string;
  total_credits: string;
  is_balanced: boolean;
  warning: string | null;
}

function fmt(amount: string) {
  const n = parseFloat(amount);
  return n === 0 ? "—" : new Intl.NumberFormat("en-US", { minimumFractionDigits: 2 }).format(n);
}

export function JournalEntriesDrawer({ runId, onClose }: { runId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["payroll-run-journal-entries", runId],
    queryFn: async () => (await apiClient.get<JournalEntriesData>(`/payroll/runs/${runId}/journal-entries`)).data,
  });

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-lg flex-col bg-[hsl(var(--background))] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div>
            <h2 className="font-heading text-lg font-semibold">Journal Entries</h2>
            {data && <p className="text-xs text-[hsl(var(--foreground-muted))]">{data.run_name}</p>}
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {isLoading || !data ? (
            <p className="text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>
          ) : (
            <>
              {data.warning && (
                <div className="mb-4 flex items-start gap-2 rounded-lg border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning-subtle))] p-3">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[hsl(var(--warning))]" />
                  <p className="text-xs text-[hsl(var(--foreground-subtle))]">{data.warning}</p>
                </div>
              )}

              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--foreground-muted))]">
                    <th className="pb-2 font-medium">Account</th>
                    <th className="pb-2 text-right font-medium">Debit</th>
                    <th className="pb-2 text-right font-medium">Credit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[hsl(var(--border))]">
                  {data.entries.map((e) => (
                    <tr key={e.purpose}>
                      <td className="py-2">
                        <p>{e.account_name}</p>
                        <p className="font-mono text-[11px] text-[hsl(var(--foreground-muted))]">{e.account_code}</p>
                      </td>
                      <td className="py-2 text-right font-mono">{fmt(e.debit)}</td>
                      <td className="py-2 text-right font-mono">{fmt(e.credit)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-[hsl(var(--border))] font-semibold">
                    <td className="pt-2">Total</td>
                    <td className="pt-2 text-right font-mono">{fmt(data.total_debits)}</td>
                    <td className="pt-2 text-right font-mono">{fmt(data.total_credits)}</td>
                  </tr>
                </tfoot>
              </table>

              <div className="mt-4 flex items-center gap-1.5 text-xs">
                <span className={data.is_balanced ? "text-[hsl(var(--success))]" : "text-[hsl(var(--destructive))]"}>
                  {data.is_balanced ? "✓ Balanced" : "✗ Not balanced — this should never happen, report it"}
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

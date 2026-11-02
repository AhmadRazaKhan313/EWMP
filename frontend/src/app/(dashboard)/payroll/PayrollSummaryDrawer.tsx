"use client";

import { X, AlertTriangle, Download } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button } from "@/components/atoms";

interface Summary {
  run: { id: string; name: string; status: string; currency: string; period_start: string; period_end: string; pay_date: string };
  totals: { employee_count: number; gross: string; deductions: string; net: string; average_net: string };
  attendance: { absent_days: string; leave_days: string; unpaid_leave_days: string; overtime_hours: string };
  by_component: { type: string; code: string; name: string; total: string; employee_count: number }[];
  by_department: { department_id: string | null; department_name: string; employee_count: number; gross: string; deductions: string; net: string }[];
  matches_run_totals: boolean;
}

const TYPE_LABEL: Record<string, string> = {
  earning: "Earnings",
  deduction: "Deductions",
  employer_contribution: "Employer contributions",
};

function money(amount: string, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(parseFloat(amount));
}

export function PayrollSummaryDrawer({ runId, onClose }: { runId: string; onClose: () => void }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["payroll-run-summary", runId],
    queryFn: async () => (await apiClient.get<Summary>(`/payroll/runs/${runId}/summary`)).data,
  });

  async function downloadCsv() {
    try {
      const res = await apiClient.get(`/payroll/runs/${runId}/summary/csv`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `payroll-summary-${data?.run.name ?? runId}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Could not download the summary");
    }
  }

  const groups = data
    ? Object.entries(
        data.by_component.reduce<Record<string, Summary["by_component"]>>((acc, c) => {
          (acc[c.type] ??= []).push(c);
          return acc;
        }, {}),
      )
    : [];

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-2xl flex-col bg-[hsl(var(--background))] shadow-2xl" role="dialog" aria-label="Payroll summary">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div>
            <h2 className="font-heading text-lg font-semibold">Payroll Summary</h2>
            {data && <p className="text-xs text-[hsl(var(--foreground-muted))]">{data.run.name} · {data.run.period_start} to {data.run.period_end}</p>}
          </div>
          <div className="flex items-center gap-2">
            {data && <Button variant="outline" size="sm" icon={<Download size={13} />} onClick={downloadCsv}>CSV</Button>}
            <button onClick={onClose} aria-label="Close" className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]">
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          {isError && <p className="text-sm text-[hsl(var(--destructive))]">Could not load the summary.</p>}
          {isLoading && <p className="text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>}
          {data && (
            <>
              {!data.matches_run_totals && (
                <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning-subtle))] p-3">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[hsl(var(--warning))]" />
                  <p className="text-xs text-[hsl(var(--foreground-subtle))]">
                    The run header totals differ from the sum of its payslips. Regenerate the payslips before paying.
                  </p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  ["Employees", String(data.totals.employee_count)],
                  ["Gross", money(data.totals.gross, data.run.currency)],
                  ["Deductions", money(data.totals.deductions, data.run.currency)],
                  ["Net pay", money(data.totals.net, data.run.currency)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-lg border border-[hsl(var(--border))] p-3">
                    <p className="text-xs text-[hsl(var(--foreground-muted))]">{label}</p>
                    <p className="mt-1 text-sm font-semibold">{value}</p>
                  </div>
                ))}
              </div>

              <p className="text-xs text-[hsl(var(--foreground-muted))]">
                Average net {money(data.totals.average_net, data.run.currency)} · Absent {data.attendance.absent_days} d ·
                Leave {data.attendance.leave_days} d · Unpaid leave {data.attendance.unpaid_leave_days} d · Overtime {data.attendance.overtime_hours} h
              </p>

              <section>
                <h3 className="mb-2 text-sm font-semibold">By component</h3>
                {groups.length === 0 && <p className="text-sm text-[hsl(var(--foreground-muted))]">No payslip lines yet.</p>}
                {groups.map(([type, rows]) => (
                  <div key={type} className="mb-3">
                    <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[hsl(var(--foreground-muted))]">{TYPE_LABEL[type] ?? type}</p>
                    <table className="w-full text-sm">
                      <tbody>
                        {rows.map((c) => (
                          <tr key={`${c.code}-${c.name}`} className="border-b border-[hsl(var(--border))] last:border-0">
                            <td className="py-2">{c.name}</td>
                            <td className="py-2 text-right text-xs text-[hsl(var(--foreground-muted))]">{c.employee_count} emp</td>
                            <td className="py-2 text-right font-medium">{money(c.total, data.run.currency)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
              </section>

              <section>
                <h3 className="mb-2 text-sm font-semibold">By department</h3>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-[hsl(var(--foreground-muted))]">
                      <th className="pb-2 font-medium">Department</th>
                      <th className="pb-2 text-right font-medium">Emp</th>
                      <th className="pb-2 text-right font-medium">Gross</th>
                      <th className="pb-2 text-right font-medium">Net</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_department.map((d) => (
                      <tr key={d.department_id ?? "none"} className="border-b border-[hsl(var(--border))] last:border-0">
                        <td className="py-2">{d.department_name}</td>
                        <td className="py-2 text-right">{d.employee_count}</td>
                        <td className="py-2 text-right">{money(d.gross, data.run.currency)}</td>
                        <td className="py-2 text-right font-medium">{money(d.net, data.run.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </>
          )}
        </div>
      </div>
    </>
  );
}

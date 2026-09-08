"use client";

import { X, TrendingUp, TrendingDown, Building2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "@/services/api-client";
import { Badge } from "@/components/atoms";

interface PayslipLine {
  code: string;
  name: string;
  amount: string;
  is_taxable: boolean;
}

interface PayslipDetail {
  id: string;
  employee_name: string;
  employee_code: string | null;
  run: { name: string; period_start: string; period_end: string; pay_date: string; currency: string };
  status: string;
  working_days: number;
  present_days: string;
  absent_days: string;
  leave_days: string;
  unpaid_leave_days: string;
  overtime_hours: string;
  gross_salary: string;
  total_deductions: string;
  net_salary: string;
  earnings: PayslipLine[];
  deductions: PayslipLine[];
  employer_contributions: PayslipLine[];
}

function fmt(amount: string, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(parseFloat(amount));
}

function LineRow({ line, currency, tone }: { line: PayslipLine; currency: string; tone: "earning" | "deduction" | "contribution" }) {
  const color =
    tone === "earning" ? "text-[hsl(var(--foreground))]" :
    tone === "deduction" ? "text-[hsl(var(--destructive))]" : "text-[hsl(var(--foreground-subtle))]";
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="flex items-center gap-2">
        <span className="text-sm">{line.name}</span>
        {!line.is_taxable && <Badge variant="default">Non-taxable</Badge>}
      </div>
      <span className={`font-mono text-sm font-medium ${color}`}>
        {tone === "deduction" ? "-" : ""}{fmt(line.amount, currency)}
      </span>
    </div>
  );
}

export function PayslipDrawer({ payslipId, onClose }: { payslipId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["payslip", payslipId],
    queryFn: async () => (await apiClient.get<PayslipDetail>(`/payroll/payslips/${payslipId}`)).data,
  });

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-lg flex-col bg-[hsl(var(--background))] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div>
            <h2 className="font-heading text-lg font-semibold">{data?.employee_name ?? "Payslip"}</h2>
            {data && (
              <p className="text-xs text-[hsl(var(--foreground-muted))]">
                {data.employee_code} &nbsp;·&nbsp; {data.run.name}
              </p>
            )}
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={16} />
          </button>
        </div>

        {isLoading || !data ? (
          <div className="flex-1 p-6 text-sm text-[hsl(var(--foreground-muted))]">Loading…</div>
        ) : (
          <div className="flex-1 overflow-y-auto px-6 py-5">
            {/* Attendance summary — grounds the numbers below in what was actually worked */}
            <div className="mb-5 grid grid-cols-4 gap-2 rounded-lg bg-[hsl(var(--accent))] p-3 text-center">
              <div>
                <p className="text-sm font-semibold">{data.working_days}</p>
                <p className="text-[10px] text-[hsl(var(--foreground-muted))]">Working days</p>
              </div>
              <div>
                <p className="text-sm font-semibold">{data.present_days}</p>
                <p className="text-[10px] text-[hsl(var(--foreground-muted))]">Present</p>
              </div>
              <div>
                <p className="text-sm font-semibold">{data.leave_days}</p>
                <p className="text-[10px] text-[hsl(var(--foreground-muted))]">Leave {data.unpaid_leave_days !== "0.00" && `(${data.unpaid_leave_days} unpaid)`}</p>
              </div>
              <div>
                <p className="text-sm font-semibold">{data.absent_days}</p>
                <p className="text-[10px] text-[hsl(var(--foreground-muted))]">Absent</p>
              </div>
            </div>

            {/* Earnings */}
            <div className="mb-4">
              <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--foreground-muted))]">
                <TrendingUp size={12} /> Earnings
              </div>
              <div className="divide-y divide-[hsl(var(--border))]">
                {data.earnings.map((l) => <LineRow key={l.code} line={l} currency={data.run.currency} tone="earning" />)}
              </div>
              <div className="mt-1.5 flex items-center justify-between border-t border-[hsl(var(--border))] pt-1.5">
                <span className="text-sm font-semibold">Gross Earnings</span>
                <span className="font-mono text-sm font-semibold">{fmt(data.gross_salary, data.run.currency)}</span>
              </div>
            </div>

            {/* Deductions */}
            <div className="mb-4">
              <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--foreground-muted))]">
                <TrendingDown size={12} /> Deductions
              </div>
              {data.deductions.length === 0 ? (
                <p className="py-1.5 text-sm text-[hsl(var(--foreground-muted))]">No deductions this period</p>
              ) : (
                <div className="divide-y divide-[hsl(var(--border))]">
                  {data.deductions.map((l) => <LineRow key={l.code} line={l} currency={data.run.currency} tone="deduction" />)}
                </div>
              )}
              <div className="mt-1.5 flex items-center justify-between border-t border-[hsl(var(--border))] pt-1.5">
                <span className="text-sm font-semibold">Total Deductions</span>
                <span className="font-mono text-sm font-semibold text-[hsl(var(--destructive))]">-{fmt(data.total_deductions, data.run.currency)}</span>
              </div>
            </div>

            {/* Employer contributions — informational, doesn't affect net */}
            {data.employer_contributions.length > 0 && (
              <div className="mb-4">
                <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--foreground-muted))]">
                  <Building2 size={12} /> Employer Contributions
                </div>
                <p className="mb-1 text-[11px] text-[hsl(var(--foreground-muted))]">Paid by the company — doesn't affect net pay</p>
                <div className="divide-y divide-[hsl(var(--border))]">
                  {data.employer_contributions.map((l) => <LineRow key={l.code} line={l} currency={data.run.currency} tone="contribution" />)}
                </div>
              </div>
            )}

            {/* Net */}
            <div className="mt-4 flex items-center justify-between rounded-lg bg-[hsl(var(--success-subtle))] p-4">
              <span className="text-sm font-semibold">Net Salary</span>
              <span className="font-mono text-lg font-bold text-[hsl(var(--success))]">{fmt(data.net_salary, data.run.currency)}</span>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

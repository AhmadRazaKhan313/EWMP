"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, Save, Loader2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button, Card, PageHeader } from "@/components/atoms";
import { PayrollNav } from "../PayrollNav";

interface MappingRow {
  purpose: string;
  account_code: string;
  account_name: string;
  is_configured: boolean;
}

const purposeLabel: Record<string, string> = {
  salary_expense: "Salary Expense (Debit)",
  employer_contribution_expense: "Employer Contribution Expense (Debit)",
  net_pay_payable: "Net Pay Payable (Credit)",
  tax_payable: "Tax Payable (Credit)",
  contribution_payable: "Contribution Payable (Credit)",
  loan_recovery_payable: "Loan Recovery Payable (Credit)",
  advance_recovery_payable: "Advance Recovery Payable (Credit)",
  other_deductions_payable: "Other Deductions Payable (Credit)",
};

function EditableRow({ row }: { row: MappingRow }) {
  const qc = useQueryClient();
  const [code, setCode] = useState(row.is_configured ? row.account_code : "");
  const [name, setName] = useState(row.is_configured ? row.account_name : "");

  const save = useMutation({
    mutationFn: () => apiClient.put(`/payroll/account-mappings/${row.purpose}`, { purpose: row.purpose, account_code: code, account_name: name }),
    onSuccess: () => {
      toast.success("Account mapping saved");
      void qc.invalidateQueries({ queryKey: ["account-mappings"] });
    },
    onError: () => toast.error("Could not save mapping"),
  });

  return (
    <div className="grid grid-cols-[1fr,140px,1fr,90px] items-center gap-3 border-b border-[hsl(var(--border))] py-3 last:border-0">
      <div className="flex items-center gap-2">
        {row.is_configured ? (
          <CheckCircle2 size={14} className="shrink-0 text-[hsl(var(--success))]" />
        ) : (
          <AlertTriangle size={14} className="shrink-0 text-[hsl(var(--warning))]" />
        )}
        <span className="text-sm">{purposeLabel[row.purpose] ?? row.purpose}</span>
      </div>
      <input
        value={code}
        onChange={(e) => setCode(e.target.value)}
        placeholder="Account code"
        className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1.5 text-sm font-mono outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1"
      />
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Account name"
        className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1"
      />
      <Button size="sm" variant="outline" disabled={!code.trim() || !name.trim() || save.isPending} onClick={() => save.mutate()}>
        {save.isPending ? <Loader2 size={12} className="animate-spin" /> : "Save"}
      </Button>
    </div>
  );
}

export default function PayrollAccountingPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["account-mappings"],
    queryFn: async () => (await apiClient.get<{ items: MappingRow[] }>("/payroll/account-mappings")).data,
  });

  const rows = data?.items ?? [];
  const unmappedCount = rows.filter((r) => !r.is_configured).length;

  return (
    <div className="space-y-6">
      <PageHeader title="Payroll" description="Manage salary processing, payslips, and compensation." />
      <PayrollNav />

      <Card className="max-w-3xl">
        <div className="mb-1 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Chart of Accounts Mapping</h3>
          {unmappedCount > 0 && (
            <span className="flex items-center gap-1 text-xs text-[hsl(var(--warning))]">
              <AlertTriangle size={12} /> {unmappedCount} unmapped
            </span>
          )}
        </div>
        <p className="mb-4 text-xs text-[hsl(var(--foreground-muted))]">
          Map each journal-entry purpose to your real chart-of-account codes. Unmapped purposes use a clearly-labeled
          placeholder until configured — journal entries generated from an unmapped purpose should be remapped before posting.
        </p>

        {isLoading ? (
          <p className="text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>
        ) : (
          <div>
            <div className="grid grid-cols-[1fr,140px,1fr,90px] gap-3 border-b border-[hsl(var(--border))] pb-2 text-xs font-medium text-[hsl(var(--foreground-muted))]">
              <span>Purpose</span>
              <span>Account Code</span>
              <span>Account Name</span>
              <span />
            </div>
            {rows.map((row) => <EditableRow key={row.purpose} row={row} />)}
          </div>
        )}
      </Card>

      <Card className="max-w-3xl">
        <h3 className="mb-2 text-sm font-semibold">How journal entries are generated</h3>
        <p className="text-xs text-[hsl(var(--foreground-muted))]">
          Open any locked payroll run and use <span className="font-medium text-[hsl(var(--foreground))]">Journal Entries</span> to
          preview the debit/credit breakdown for that run. Debits (salary expense, employer contribution expense) always equal
          credits (net pay payable, tax payable, contribution payable, loan/advance recovery, other deductions) — the engine
          guarantees this by construction.
        </p>
      </Card>
    </div>
  );
}
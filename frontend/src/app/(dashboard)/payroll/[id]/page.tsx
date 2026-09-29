"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import type { ColumnDef } from "@tanstack/react-table";
import { ArrowLeft, Play, CheckCircle2, Loader2, Users, FileText, Lock, Unlock, Undo2, History, BookOpen, Banknote, Download } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Button, Card, EmptyState } from "@/components/atoms";
import { PayslipDrawer } from "../PayslipDrawer";
import { ReasonDialog } from "../ReasonDialog";
import { AuditLogDrawer } from "../AuditLogDrawer";
import { JournalEntriesDrawer } from "../JournalEntriesDrawer";
import { PaymentBatchDrawer } from "../PaymentBatchDrawer";

interface RunDetail {
  id: string; name: string; period_start: string; period_end: string; pay_date: string;
  status: "draft" | "processing" | "review" | "approved" | "locked" | "reopened" | "paid" | "cancelled";
  currency: string; total_gross: string; total_deductions: string; total_net: string; employee_count: number;
}

interface PayslipRow {
  id: string; employee_id: string; employee_name: string;
  gross_salary: string; total_deductions: string; net_salary: string; status: string;
}

const statusConfig: Record<string, { label: string; variant: "default" | "warning" | "info" | "success" | "error" }> = {
  draft:      { label: "Draft",      variant: "default" },
  processing: { label: "Processing", variant: "info" },
  review:     { label: "Ready for Review", variant: "warning" },
  approved:   { label: "Approved",   variant: "success" },
  locked:     { label: "Locked",     variant: "success" },
  reopened:   { label: "Reopened",   variant: "warning" },
  paid:       { label: "Paid",       variant: "success" },
  cancelled:  { label: "Cancelled",  variant: "error" },
};

function fmt(amount: string, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(parseFloat(amount));
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
}

export default function PayrollRunDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const [selectedPayslipId, setSelectedPayslipId] = useState<string | null>(null);
  const [showAuditLog, setShowAuditLog] = useState(false);
  const [showReopenDialog, setShowReopenDialog] = useState(false);
  const [showReverseDialog, setShowReverseDialog] = useState(false);
  const [showJournalEntries, setShowJournalEntries] = useState(false);
  const [showPaymentBatch, setShowPaymentBatch] = useState(false);

  const { data: run, isLoading: runLoading } = useQuery({
    queryKey: ["payroll-run", params.id],
    queryFn: async () => (await apiClient.get<RunDetail>(`/payroll/runs/${params.id}`)).data,
  });

  const { data: payslipsData, isLoading: payslipsLoading } = useQuery({
    queryKey: ["payroll-run-payslips", params.id],
    queryFn: async () => (await apiClient.get<{ items: PayslipRow[]; total: number }>(`/payroll/runs/${params.id}/payslips`)).data,
    enabled: !!run && run.status !== "draft",
  });

  const generate = useMutation({
    mutationFn: () => apiClient.post(`/payroll/runs/${params.id}/generate`),
    onSuccess: () => {
      toast.success("Payslips generated — review the numbers below");
      void qc.invalidateQueries({ queryKey: ["payroll-run", params.id] });
      void qc.invalidateQueries({ queryKey: ["payroll-run-payslips", params.id] });
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not generate payslips";
      toast.error(msg);
    },
  });

  const approve = useMutation({
    mutationFn: () => apiClient.post(`/payroll/runs/${params.id}/approve`),
    onSuccess: (res) => {
      if (res.data.fully_approved === false) {
        toast.success(`Approval recorded — ${res.data.levels_approved}/${res.data.levels_required} levels approved so far`);
      } else {
        toast.success("Payroll run approved");
      }
      void qc.invalidateQueries({ queryKey: ["payroll-run", params.id] });
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not approve run";
      toast.error(msg);
    },
  });

  const finalize = useMutation({
    mutationFn: () => apiClient.post(`/payroll/runs/${params.id}/finalize`),
    onSuccess: () => {
      toast.success("Run finalized and locked — a snapshot of every rate/rule used was saved");
      void qc.invalidateQueries({ queryKey: ["payroll-run", params.id] });
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not finalize run";
      toast.error(msg);
    },
  });

  const reopen = useMutation({
    mutationFn: (reason: string) => apiClient.post(`/payroll/runs/${params.id}/reopen`, { reason }),
    onSuccess: () => {
      toast.success("Run reopened for correction");
      setShowReopenDialog(false);
      void qc.invalidateQueries({ queryKey: ["payroll-run", params.id] });
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not reopen run";
      toast.error(msg);
    },
  });

  const reverse = useMutation({
    mutationFn: (reason: string) => apiClient.post(`/payroll/runs/${params.id}/reverse`, { reason }),
    onSuccess: () => {
      toast.success("Run reversed — all payslips voided");
      setShowReverseDialog(false);
      void qc.invalidateQueries({ queryKey: ["payroll-run", params.id] });
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not reverse run";
      toast.error(msg);
    },
  });

  const payslips = payslipsData?.items ?? [];

  const columns: ColumnDef<PayslipRow, unknown>[] = [
    { header: "Employee", accessorKey: "employee_name", cell: ({ getValue }) => <span className="font-medium">{getValue<string>()}</span> },
    {
      header: "Gross", accessorKey: "gross_salary",
      cell: ({ row, getValue }) => <span className="font-mono text-sm">{fmt(getValue<string>(), run?.currency ?? "USD")}</span>,
    },
    {
      header: "Deductions", accessorKey: "total_deductions",
      cell: ({ getValue }) => <span className="font-mono text-sm text-[hsl(var(--destructive))]">-{fmt(getValue<string>(), run?.currency ?? "USD")}</span>,
    },
    {
      header: "Net Pay", accessorKey: "net_salary",
      cell: ({ getValue }) => <span className="font-mono text-sm font-semibold text-[hsl(var(--success))]">{fmt(getValue<string>(), run?.currency ?? "USD")}</span>,
    },
  ];

  if (runLoading || !run) {
    return <div className="text-sm text-[hsl(var(--foreground-muted))]">Loading…</div>;
  }

  const cfg = statusConfig[run.status] ?? { label: run.status, variant: "default" as const };

  return (
    <div className="space-y-6">
      <button
        onClick={() => router.push("/payroll")}
        className="flex items-center gap-1.5 text-sm text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
      >
        <ArrowLeft size={14} /> Back to Payroll
      </button>

      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-heading text-xl font-semibold tracking-tight">{run.name}</h1>
            <Badge variant={cfg.variant}>{cfg.label}</Badge>
          </div>
          <p className="mt-0.5 text-sm text-[hsl(var(--foreground-muted))]">
            {formatDate(run.period_start)} – {formatDate(run.period_end)} &nbsp;·&nbsp; Pay date {formatDate(run.pay_date)}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" icon={<History size={13} />} onClick={() => setShowAuditLog(true)}>
            Audit Log
          </Button>
          {run.status !== "draft" && (
            <>
              <Button variant="outline" size="sm" icon={<BookOpen size={13} />} onClick={() => setShowJournalEntries(true)}>
                Journal Entries
              </Button>
              <Button
                variant="outline" size="sm" icon={<Download size={13} />}
                onClick={() => window.open(`${apiClient.defaults.baseURL}/payroll/runs/${params.id}/register/csv`, "_blank")}
              >
                Register CSV
              </Button>
            </>
          )}
          {(run.status === "approved" || run.status === "locked") && (
            <Button variant="outline" size="sm" icon={<Banknote size={13} />} onClick={() => setShowPaymentBatch(true)}>
              Payment Batch
            </Button>
          )}
          {(run.status === "draft" || run.status === "review" || run.status === "reopened") && (
            <Button onClick={() => generate.mutate()} disabled={generate.isPending} icon={generate.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}>
              {run.status === "draft" ? "Generate Payslips" : "Regenerate Payslips"}
            </Button>
          )}
          {run.status === "review" && (
            <Button variant="secondary" onClick={() => approve.mutate()} disabled={approve.isPending} icon={approve.isPending ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}>
              Approve Run
            </Button>
          )}
          {run.status === "approved" && (
            <Button variant="secondary" onClick={() => finalize.mutate()} disabled={finalize.isPending} icon={finalize.isPending ? <Loader2 size={14} className="animate-spin" /> : <Lock size={14} />}>
              Finalize & Lock
            </Button>
          )}
          {run.status === "locked" && (
            <Button variant="outline" onClick={() => setShowReopenDialog(true)} icon={<Unlock size={14} />}>
              Reopen
            </Button>
          )}
          {(run.status === "review" || run.status === "approved" || run.status === "locked") && (
            <Button variant="destructive" onClick={() => setShowReverseDialog(true)} icon={<Undo2 size={14} />}>
              Reverse
            </Button>
          )}
        </div>
      </div>

      {run.status !== "draft" && (
        <div className="grid grid-cols-4 gap-4">
          <Card>
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--info-subtle))]">
                <Users size={16} className="text-[hsl(var(--info))]" />
              </div>
              <div>
                <p className="text-xl font-semibold font-heading">{run.employee_count}</p>
                <p className="text-xs text-[hsl(var(--foreground-muted))]">Employees</p>
              </div>
            </div>
          </Card>
          <Card>
            <p className="text-xl font-semibold font-heading font-mono">{fmt(run.total_gross, run.currency)}</p>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">Total gross</p>
          </Card>
          <Card>
            <p className="text-xl font-semibold font-heading font-mono text-[hsl(var(--destructive))]">-{fmt(run.total_deductions, run.currency)}</p>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">Total deductions</p>
          </Card>
          <Card>
            <p className="text-xl font-semibold font-heading font-mono text-[hsl(var(--success))]">{fmt(run.total_net, run.currency)}</p>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">Total net pay</p>
          </Card>
        </div>
      )}

      {run.status === "draft" ? (
        <Card>
          <EmptyState
            icon={FileText}
            title="Not generated yet"
            description="Click Generate Payslips to calculate salaries for every active employee in this period."
          />
        </Card>
      ) : (
        <DataTable
          data={payslips}
          columns={columns}
          isLoading={payslipsLoading}
          searchPlaceholder="Search employees…"
          onRowClick={(row) => setSelectedPayslipId(row.id)}
          emptyState={<EmptyState icon={FileText} title="No payslips" description="No employees were eligible for this run." />}
        />
      )}

      {selectedPayslipId && (
        <PayslipDrawer payslipId={selectedPayslipId} onClose={() => setSelectedPayslipId(null)} />
      )}

      {showAuditLog && (
        <AuditLogDrawer runId={params.id} onClose={() => setShowAuditLog(false)} />
      )}

      {showJournalEntries && (
        <JournalEntriesDrawer runId={params.id} onClose={() => setShowJournalEntries(false)} />
      )}

      {showPaymentBatch && (
        <PaymentBatchDrawer runId={params.id} onClose={() => setShowPaymentBatch(false)} />
      )}

      {showReopenDialog && (
        <ReasonDialog
          title="Reopen this locked run?"
          description="This will unlock the run for correction. The reason is recorded in the audit log."
          confirmLabel="Reopen"
          isPending={reopen.isPending}
          onConfirm={(reason) => reopen.mutate(reason)}
          onClose={() => setShowReopenDialog(false)}
        />
      )}

      {showReverseDialog && (
        <ReasonDialog
          title="Reverse this payroll run?"
          description="This voids the run and every payslip in it. This cannot be undone — use it for mistakes, not corrections to a paid run."
          confirmLabel="Reverse Run"
          destructive
          isPending={reverse.isPending}
          onConfirm={(reason) => reverse.mutate(reason)}
          onClose={() => setShowReverseDialog(false)}
        />
      )}
    </div>
  );
}
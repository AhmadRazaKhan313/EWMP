"use client";

import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { DollarSign, Play, CheckCircle, Clock, Plus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";
import { PayrollNav } from "./PayrollNav";
import { NewPayrollRunDrawer } from "./NewPayrollRunDrawer";

interface PayrollRun {
  id: string;
  name: string;
  period_start: string;
  period_end: string;
  pay_date: string;
  status: "draft" | "processing" | "review" | "approved" | "paid" | "cancelled";
  total_gross: string;
  total_deductions: string;
  total_net: string;
  employee_count: number;
  currency: string;
}

const statusConfig: Record<string, { label: string; variant: "default" | "warning" | "info" | "success" | "error" }> = {
  draft:      { label: "Draft",      variant: "default" },
  processing: { label: "Processing", variant: "info" },
  review:     { label: "In Review",  variant: "warning" },
  approved:   { label: "Approved",   variant: "success" },
  paid:       { label: "Paid",       variant: "success" },
  cancelled:  { label: "Cancelled",  variant: "error" },
};

function fmt(amount: string, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(parseFloat(amount));
}

export default function PayrollPage() {
  const router = useRouter();
  const [showNewRun, setShowNewRun] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["payroll-runs"],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: PayrollRun[]; total: number }>("/payroll/runs");
      return data;
    },
  });

  const runs = data?.items ?? [];
  const totalPaidThisYear = runs
    .filter((r) => r.status === "paid")
    .reduce((s, r) => s + parseFloat(r.total_net), 0);

  const columns: ColumnDef<PayrollRun, unknown>[] = [
    {
      header: "Payroll Run",
      accessorKey: "name",
      cell: ({ row }) => (
        <div>
          <p className="font-medium">{row.original.name}</p>
          <p className="text-xs text-[hsl(var(--foreground-muted))]">
            {new Date(row.original.period_start).toLocaleDateString("en-US", { month: "short", day: "numeric" })} –{" "}
            {new Date(row.original.period_end).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
          </p>
        </div>
      ),
    },
    {
      header: "Pay Date",
      accessorKey: "pay_date",
      cell: ({ getValue }) => (
        <span className="text-sm text-[hsl(var(--foreground-subtle))]">
          {new Date(getValue<string>()).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" })}
        </span>
      ),
    },
    {
      header: "Employees",
      accessorKey: "employee_count",
      cell: ({ getValue }) => <span className="font-mono text-sm">{getValue<number>()}</span>,
    },
    {
      header: "Gross",
      accessorKey: "total_gross",
      cell: ({ row }) => (
        <span className="font-mono text-sm">{fmt(row.original.total_gross, row.original.currency)}</span>
      ),
    },
    {
      header: "Deductions",
      accessorKey: "total_deductions",
      cell: ({ row }) => (
        <span className="font-mono text-sm text-[hsl(var(--destructive))]">
          -{fmt(row.original.total_deductions, row.original.currency)}
        </span>
      ),
    },
    {
      header: "Net Pay",
      accessorKey: "total_net",
      cell: ({ row }) => (
        <span className="font-mono text-sm font-semibold text-[hsl(var(--success))]">
          {fmt(row.original.total_net, row.original.currency)}
        </span>
      ),
    },
    {
      header: "Status",
      accessorKey: "status",
      cell: ({ getValue }) => {
        const s = getValue<string>();
        const cfg = statusConfig[s] ?? { label: s, variant: "default" as const };
        return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
      },
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payroll"
        description="Manage salary processing, payslips, and compensation."
        action={
          <Button icon={<Plus size={15} />} onClick={() => setShowNewRun(true)}>
            New Payroll Run
          </Button>
        }
      />

      <PayrollNav />

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]">
              <DollarSign size={16} className="text-[hsl(var(--success))]" />
            </div>
            <div>
              <p className="text-xl font-semibold font-heading">
                {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact" }).format(totalPaidThisYear)}
              </p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">Total paid this year</p>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--warning-subtle))]">
              <Clock size={16} className="text-[hsl(var(--warning))]" />
            </div>
            <div>
              <p className="text-xl font-semibold font-heading">
                {runs.filter((r) => ["draft", "processing", "review"].includes(r.status)).length}
              </p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">Runs in progress</p>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--info-subtle))]">
              <CheckCircle size={16} className="text-[hsl(var(--info))]" />
            </div>
            <div>
              <p className="text-xl font-semibold font-heading">{runs.filter((r) => r.status === "paid").length}</p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">Completed runs</p>
            </div>
          </div>
        </Card>
      </div>

      <DataTable
        data={runs}
        columns={columns}
        isLoading={isLoading}
        searchPlaceholder="Search payroll runs…"
        onRowClick={(row) => router.push(`/payroll/${row.id}`)}
        emptyState={
          <EmptyState
            icon={DollarSign}
            title="No payroll runs yet"
            description="Create your first payroll run to start processing salaries."
            action={<Button icon={<Plus size={14} />} onClick={() => setShowNewRun(true)}>New Payroll Run</Button>}
          />
        }
      />

      {showNewRun && <NewPayrollRunDrawer onClose={() => setShowNewRun(false)} />}
    </div>
  );
}

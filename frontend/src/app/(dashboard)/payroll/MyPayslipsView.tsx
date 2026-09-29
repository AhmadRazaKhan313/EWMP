"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { Download, Wallet } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Card, EmptyState, PageHeader } from "@/components/atoms";

interface MyPayslip {
  id: string;
  status: "draft" | "generated" | "sent" | "paid" | "reversed";
  gross_salary: string;
  total_deductions: string;
  net_salary: string;
  run: {
    id: string;
    name: string;
    period_start: string;
    period_end: string;
    pay_date: string;
    currency: string;
  };
}

const statusConfig: Record<string, { label: string; variant: "default" | "warning" | "info" | "success" | "error" }> = {
  draft: { label: "Draft", variant: "default" },
  generated: { label: "Generated", variant: "info" },
  sent: { label: "Sent", variant: "info" },
  paid: { label: "Paid", variant: "success" },
  reversed: { label: "Reversed", variant: "error" },
};

function fmt(amount: string, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(parseFloat(amount));
}

/** Same blob-download pattern as downloadEmployeeDocument /
 * useScreenshotImage — the PDF endpoint needs the same Bearer auth as
 * everything else, so a plain link can't be used. */
async function downloadPayslipPdf(payslipId: string, fileName: string) {
  try {
    const response = await apiClient.get(`/payroll/payslips/${payslipId}/pdf`, { responseType: "blob" });
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch {
    toast.error("Could not download payslip");
  }
}

export function MyPayslipsView() {
  const { data, isLoading } = useQuery({
    queryKey: ["my-payslips"],
    queryFn: async () => {
      // GET /payroll/payslips/me — self-service, no payroll.view needed.
      // See its docstring in app/api/v1/hrms/payroll.py for why this
      // exists (GET /runs is admin-only; there was no other way for an
      // employee to browse their own payslip history).
      const { data } = await apiClient.get<{ items: MyPayslip[]; total: number }>("/payroll/payslips/me");
      return data;
    },
  });

  const payslips = data?.items ?? [];
  const totalPaidThisYear = payslips
    .filter((p) => p.status === "paid")
    .reduce((s, p) => s + parseFloat(p.net_salary), 0);

  const columns: ColumnDef<MyPayslip, unknown>[] = [
    {
      header: "Pay Period",
      accessorFn: (row) => row.run.name,
      id: "period",
      cell: ({ row }) => (
        <div>
          <p className="font-medium">{row.original.run.name}</p>
          <p className="text-xs text-[hsl(var(--foreground-muted))]">
            {new Date(row.original.run.period_start).toLocaleDateString("en-US", { month: "short", day: "numeric" })} –{" "}
            {new Date(row.original.run.period_end).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
          </p>
        </div>
      ),
    },
    {
      header: "Pay Date",
      accessorFn: (row) => row.run.pay_date,
      id: "pay_date",
      cell: ({ row }) => (
        <span className="text-sm text-[hsl(var(--foreground-subtle))]">
          {new Date(row.original.run.pay_date).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" })}
        </span>
      ),
    },
    {
      header: "Gross",
      accessorKey: "gross_salary",
      cell: ({ row }) => (
        <span className="font-mono text-sm">{fmt(row.original.gross_salary, row.original.run.currency)}</span>
      ),
    },
    {
      header: "Deductions",
      accessorKey: "total_deductions",
      cell: ({ row }) => (
        <span className="font-mono text-sm text-[hsl(var(--destructive))]">
          -{fmt(row.original.total_deductions, row.original.run.currency)}
        </span>
      ),
    },
    {
      header: "Net Pay",
      accessorKey: "net_salary",
      cell: ({ row }) => (
        <span className="font-mono text-sm font-semibold text-[hsl(var(--success))]">
          {fmt(row.original.net_salary, row.original.run.currency)}
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
    {
      id: "actions",
      header: "",
      enableSorting: false,
      cell: ({ row }) => (
        <button
          type="button"
          title="Download payslip PDF"
          aria-label="Download payslip PDF"
          onClick={() =>
            void downloadPayslipPdf(row.original.id, `payslip-${row.original.run.pay_date}.pdf`)
          }
          className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]"
        >
          <Download size={14} />
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="My Payslips" description="Your salary history and payslip downloads." />

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]">
              <Wallet size={16} className="text-[hsl(var(--success))]" />
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
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--info-subtle))]">
              <Wallet size={16} className="text-[hsl(var(--info))]" />
            </div>
            <div>
              <p className="text-xl font-semibold font-heading">{payslips.length}</p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">Payslips on file</p>
            </div>
          </div>
        </Card>
      </div>

      <DataTable
        data={payslips}
        columns={columns}
        isLoading={isLoading}
        searchPlaceholder="Search payslips…"
        emptyState={
          <EmptyState
            icon={Wallet}
            title="No payslips yet"
            description="Your payslips will show up here once payroll has been processed for you."
          />
        }
      />
    </div>
  );
}

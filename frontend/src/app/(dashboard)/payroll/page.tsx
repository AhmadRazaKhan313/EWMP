"use client";

import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { DollarSign, CheckCircle, Clock, Plus, Pencil, Trash2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";
import { cn } from "@/utils/cn";
import { useAuthStore } from "@/store/auth.store";
import { PayrollNav } from "./PayrollNav";
import { MyPayslipsView } from "./MyPayslipsView";

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

interface NewPayrollRunInput {
  name: string;
  period_start: string;
  period_end: string;
  pay_date: string;
  currency: string;
}

type PayrollRunFormMode = "create" | "edit";

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

/** Matches backend's CreatePayrollRunRequest exactly (name, period_start,
 * period_end, pay_date, currency) — see POST /payroll/runs. */
function NewPayrollRunForm({
  onSubmit, onCancel, isLoading, initialRun, mode = "create",
}: {
  onSubmit: (input: NewPayrollRunInput) => void;
  onCancel: () => void;
  isLoading?: boolean;
  initialRun?: PayrollRun;
  mode?: PayrollRunFormMode;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [name, setName] = useState(initialRun?.name ?? "");
  const [periodStart, setPeriodStart] = useState(initialRun?.period_start ?? today);
  const [periodEnd, setPeriodEnd] = useState(initialRun?.period_end ?? today);
  const [payDate, setPayDate] = useState(initialRun?.pay_date ?? today);
  const [currency, setCurrency] = useState(initialRun?.currency ?? "USD");

  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";
  const isValid = name.trim().length > 0 && periodStart && periodEnd && payDate && periodEnd >= periodStart;

  return (
    <div className="space-y-4 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 shadow-sm">
      <h3 className="font-heading text-sm font-semibold">{mode === "edit" ? "Edit Payroll Run" : "New Payroll Run"}</h3>
      <div>
        <label className="mb-1 block text-xs font-medium">Name *</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="September 2026 Payroll"
          className={inp}
        />
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="mb-1 block text-xs font-medium">Period Start *</label>
          <input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} className={inp} />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium">Period End *</label>
          <input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} className={inp} />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium">Pay Date *</label>
          <input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} className={inp} />
        </div>
      </div>
      {periodEnd < periodStart && (
        <p className="text-xs text-[hsl(var(--destructive))]">Period end can&apos;t be before period start.</p>
      )}
      <div className="w-32">
        <label className="mb-1 block text-xs font-medium">Currency</label>
        <input
          value={currency}
          onChange={(e) => setCurrency(e.target.value.toUpperCase().slice(0, 3))}
          placeholder="USD"
          className={cn(inp, "font-mono uppercase")}
          maxLength={3}
        />
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onCancel}>Cancel</Button>
        <Button
          size="sm"
          disabled={!isValid || isLoading}
          onClick={() =>
            onSubmit({ name: name.trim(), period_start: periodStart, period_end: periodEnd, pay_date: payDate, currency })
          }
        >
          {isLoading ? (mode === "edit" ? "Saving..." : "Creating...") : (mode === "edit" ? "Save Changes" : "Create")}
        </Button>
      </div>
    </div>
  );
}

/**
 * `/payroll` used to render the same admin payroll-runs management page
 * (full runs table + an unconditional "New Payroll Run" button) for
 * EVERY signed-in user — unlike the dashboard's per-permission-gated
 * quick actions, this page itself had no permission check at all. An
 * employee with no payroll permissions who followed the dashboard's
 * "My Payslips" link landed here and saw admin controls that would only
 * 403 if actually clicked, instead of anything resembling "my payslips".
 *
 * Fixed by branching at the page level, same pattern as
 * dashboard/page.tsx's orgVisibility split: someone with payroll.view
 * (or the owner/platform-admin full-access bypass — mirrors every other
 * page's convention) gets the admin view; everyone else gets a real
 * self-service payslips view backed by GET /payroll/payslips/me.
 */
export default function PayrollPage() {
  const { hasPermission, hasRole, user } = useAuthStore();
  const canManagePayroll = !!user?.is_platform_admin || hasRole("owner") || hasPermission("payroll.view");

  return canManagePayroll ? <AdminPayrollRunsView /> : <MyPayslipsView />;
}

function AdminPayrollRunsView() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingRun, setEditingRun] = useState<PayrollRun | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["payroll-runs"],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: PayrollRun[]; total: number }>("/payroll/runs");
      return data;
    },
  });

  const createRun = useMutation({
    mutationFn: (body: NewPayrollRunInput) => apiClient.post("/payroll/runs", body),
    onSuccess: () => {
      toast.success("Payroll run created");
      void qc.invalidateQueries({ queryKey: ["payroll-runs"] });
      setShowForm(false);
    },
    onError: (err: unknown) => {
      // e.g. 403 if the signed-in user only has payroll.view, not
      // payroll.process — surfaced here rather than only in the console,
      // since the button gave no other feedback before this fix.
      const message =
        (err as { response?: { data?: { message?: string; detail?: string } } })?.response?.data?.message ??
        (err as { response?: { data?: { message?: string; detail?: string } } })?.response?.data?.detail ??
        "Could not create payroll run";
      toast.error(message);
    },
  });

  const updateRun = useMutation({
    mutationFn: ({ id, body }: { id: string; body: NewPayrollRunInput }) =>
      apiClient.patch(`/payroll/runs/${id}`, body),
    onSuccess: () => {
      toast.success("Payroll run updated");
      void qc.invalidateQueries({ queryKey: ["payroll-runs"] });
      setShowForm(false);
      setEditingRun(null);
    },
    onError: (err: unknown) => {
      const message =
        (err as { response?: { data?: { message?: string; detail?: string } } })?.response?.data?.message ??
        (err as { response?: { data?: { message?: string; detail?: string } } })?.response?.data?.detail ??
        "Could not update payroll run";
      toast.error(message);
    },
  });

  const deleteRun = useMutation({
    mutationFn: (id: string) => apiClient.delete(`/payroll/runs/${id}`),
    onSuccess: () => {
      toast.success("Payroll run deleted");
      void qc.invalidateQueries({ queryKey: ["payroll-runs"] });
    },
    onError: (err: unknown) => {
      const message =
        (err as { response?: { data?: { message?: string; detail?: string } } })?.response?.data?.message ??
        (err as { response?: { data?: { message?: string; detail?: string } } })?.response?.data?.detail ??
        "Could not delete payroll run";
      toast.error(message);
    },
  });

  function openCreateForm() {
    setEditingRun(null);
    setShowForm(true);
  }

  function openEditForm(run: PayrollRun) {
    setEditingRun(run);
    setShowForm(true);
  }

  function handleDelete(run: PayrollRun) {
    if (!window.confirm(`Delete draft payroll run "${run.name}"?`)) return;
    deleteRun.mutate(run.id);
  }

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
    {
      id: "actions",
      header: "Actions",
      enableSorting: false,
      cell: ({ row }) => {
        const isDraft = row.original.status === "draft";
        return (
          <div className="flex items-center gap-1">
            <button
              type="button"
              title={isDraft ? "Edit payroll run" : "Only draft runs can be edited"}
              aria-label={isDraft ? "Edit payroll run" : "Only draft runs can be edited"}
              disabled={!isDraft || updateRun.isPending}
              onClick={() => openEditForm(row.original)}
              className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] disabled:cursor-not-allowed disabled:opacity-35"
            >
              <Pencil size={14} />
            </button>
            <button
              type="button"
              title={isDraft ? "Delete payroll run" : "Only draft runs can be deleted"}
              aria-label={isDraft ? "Delete payroll run" : "Only draft runs can be deleted"}
              disabled={!isDraft || deleteRun.isPending}
              onClick={() => handleDelete(row.original)}
              className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--status-error-bg))] hover:text-[hsl(var(--destructive))] disabled:cursor-not-allowed disabled:opacity-35"
            >
              <Trash2 size={14} />
            </button>
          </div>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payroll"
        description="Manage salary processing, payslips, and compensation."
        action={
          <Button icon={<Plus size={15} />} onClick={openCreateForm}>
            New Payroll Run
          </Button>
        }
      />

      <PayrollNav />

      {showForm && (
        <NewPayrollRunForm
          onSubmit={(input) => {
            if (editingRun) {
              updateRun.mutate({ id: editingRun.id, body: input });
            } else {
              createRun.mutate(input);
            }
          }}
          onCancel={() => { setShowForm(false); setEditingRun(null); }}
          isLoading={createRun.isPending || updateRun.isPending}
          initialRun={editingRun ?? undefined}
          mode={editingRun ? "edit" : "create"}
        />
      )}

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
        emptyState={
          <EmptyState
            icon={DollarSign}
            title="No payroll runs yet"
            description="Create your first payroll run to start processing salaries."
            action={<Button icon={<Plus size={14} />} onClick={openCreateForm}>New Payroll Run</Button>}
          />
        }
      />
    </div>
  );
}
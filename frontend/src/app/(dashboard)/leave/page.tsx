"use client";

import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Plane, Check, X, Filter, Plus, Ban } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { AvatarLabelGroup, Badge, Button, EmptyState, PageHeader, Tabs } from "@/components/atoms";
import { ApplyLeaveModal } from "./ApplyLeaveModal";

interface LeaveRequest {
  id: string;
  employee_id: string;
  employee_name: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  total_days: number;
  duration_type?: "full_day" | "half_day" | "hourly";
  half_day_period?: "morning" | "afternoon" | null;
  hours?: number | null;
  reason: string | null;
  status: "pending" | "approved" | "rejected" | "cancelled";
  created_at: string;
}

const statusVariant: Record<string, "warning" | "success" | "error" | "default"> = {
  pending:   "warning",
  approved:  "success",
  rejected:  "error",
  cancelled: "default",
};

export default function LeavePage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [applyOpen, setApplyOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const activeFilters = [leaveTypeId, dateFrom, dateTo].filter(Boolean).length;
  const todayIso = (() => {
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  })();

  const { data: leaveTypes } = useQuery({
    queryKey: ["leave-types"],
    enabled: filtersOpen,
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: { id: string; name: string }[] }>("/leave/types");
      return data.items ?? [];
    },
  });

  const { data, isLoading } = useQuery({
    queryKey: ["leave-requests", statusFilter, leaveTypeId, dateFrom, dateTo],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: LeaveRequest[]; total: number }>(
        "/leave/requests",
        {
          params: {
            status: statusFilter || undefined,
            leave_type_id: leaveTypeId || undefined,
            date_from: dateFrom || undefined,
            date_to: dateTo || undefined,
          },
        },
      );
      return data;
    },
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => apiClient.post(`/leave/requests/${id}/approve`),
    onSuccess: () => {
      toast.success("Leave approved");
      void qc.invalidateQueries({ queryKey: ["leave-requests"] });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => apiClient.post(`/leave/requests/${id}/reject`),
    onSuccess: () => {
      toast.success("Leave rejected");
      void qc.invalidateQueries({ queryKey: ["leave-requests"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => apiClient.post(`/leave/requests/${id}/cancel`),
    onSuccess: () => {
      toast.success("Leave request cancelled");
      void qc.invalidateQueries({ queryKey: ["leave-requests"] });
    },
    onError: () => toast.error("Could not cancel this request"),
  });

  const columns: ColumnDef<LeaveRequest, unknown>[] = [
    {
      header: "Employee",
      accessorKey: "employee_name",
      cell: ({ getValue }) => <AvatarLabelGroup name={getValue<string>()} size="sm" />,
      size: 220,
    },
    {
      header: "Leave Type",
      accessorKey: "leave_type",
      cell: ({ getValue }) => (
        <span className="capitalize text-[hsl(var(--foreground-subtle))]">{getValue<string>()}</span>
      ),
    },
    {
      header: "From",
      accessorKey: "start_date",
      cell: ({ getValue }) => (
        <span className="text-sm">{new Date(getValue<string>()).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" })}</span>
      ),
    },
    {
      header: "To",
      accessorKey: "end_date",
      cell: ({ getValue }) => (
        <span className="text-sm">{new Date(getValue<string>()).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" })}</span>
      ),
    },
    {
      header: "Days",
      accessorKey: "total_days",
      cell: ({ row }) => {
        const r = row.original;
        let suffix = "";
        if (r.duration_type === "half_day") suffix = ` (${r.half_day_period ?? "half"})`;
        else if (r.duration_type === "hourly" && r.hours) suffix = ` (${r.hours}h)`;
        return (
          <span className="font-mono text-sm font-medium">
            {r.total_days}
            {suffix && <span className="ml-1 font-sans text-xs font-normal text-[hsl(var(--foreground-muted))]">{suffix}</span>}
          </span>
        );
      },
    },
    {
      header: "Status",
      accessorKey: "status",
      cell: ({ getValue }) => {
        const s = getValue<string>();
        return <Badge variant={statusVariant[s] ?? "default"}>{s.charAt(0).toUpperCase() + s.slice(1)}</Badge>;
      },
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const req = row.original;
        const canCancel =
          req.status === "pending" || (req.status === "approved" && req.start_date.slice(0, 10) >= todayIso);
        if (req.status !== "pending" && !canCancel) return null;
        return (
          <div className="flex items-center gap-1.5">
            {req.status === "pending" && (<>
            <button
              onClick={(e) => { e.stopPropagation(); approveMutation.mutate(req.id); }}
              className="flex h-7 w-7 items-center justify-center rounded-md bg-[hsl(var(--status-active-bg))] text-[hsl(var(--status-active-fg))] transition-colors hover:opacity-80"
              title="Approve"
            >
              <Check size={14} />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); rejectMutation.mutate(req.id); }}
              className="flex h-7 w-7 items-center justify-center rounded-md bg-[hsl(var(--status-error-bg))] text-[hsl(var(--status-error-fg))] transition-colors hover:opacity-80"
              title="Reject"
            >
              <X size={14} />
            </button>
            </>)}
            {canCancel && (
              <button
                onClick={(e) => { e.stopPropagation(); cancelMutation.mutate(req.id); }}
                className="flex h-7 w-7 items-center justify-center rounded-md border border-[hsl(var(--border-strong))] text-[hsl(var(--foreground-subtle))] transition-colors hover:bg-[hsl(var(--background-subtle))]"
                title="Cancel request"
                aria-label="Cancel request"
              >
                <Ban size={14} />
              </button>
            )}
          </div>
        );
      },
      size: 110,
    },
  ];

  const requests = data?.items ?? [];
  const pending  = requests.filter((r) => r.status === "pending").length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave Management"
        description="Review and manage employee leave requests."
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" icon={<Filter size={14} />} onClick={() => setFiltersOpen((o) => !o)}>
              {`Filter${activeFilters ? ` (${activeFilters})` : ""}`}
            </Button>
            <Button icon={<Plus size={14} />} onClick={() => setApplyOpen(true)}>Apply for Leave</Button>
          </div>
        }
      />

      <ApplyLeaveModal open={applyOpen} onClose={() => setApplyOpen(false)} />

      {filtersOpen && (
        <div
          data-testid="leave-filters"
          className="flex flex-wrap items-end gap-4 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4"
        >
          <label className="flex flex-col gap-1 text-sm font-medium">
            Leave type
            <select
              value={leaveTypeId}
              onChange={(e) => setLeaveTypeId(e.target.value)}
              className="h-10 min-w-[180px] rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] px-3 text-sm"
            >
              <option value="">All types</option>
              {(leaveTypes ?? []).map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">
            From date
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="h-10 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] px-3 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">
            To date
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="h-10 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] px-3 text-sm"
            />
          </label>
          <Button
            variant="outline"
            disabled={!activeFilters}
            onClick={() => { setLeaveTypeId(""); setDateFrom(""); setDateTo(""); }}
          >
            Clear filters
          </Button>
        </div>
      )}

      {/* Status filter — the shared segmented-tab pattern, per the Figma design */}
      <Tabs
        tabs={[
          { value: "", label: "All" },
          { value: "pending", label: "Pending", count: pending > 0 ? pending : undefined },
          { value: "approved", label: "Approved" },
          { value: "rejected", label: "Rejected" },
        ]}
        value={statusFilter}
        onChange={setStatusFilter}
      />

      <DataTable
        data={requests}
        columns={columns}
        isLoading={isLoading}
        searchPlaceholder="Search by employee or leave type…"
        emptyState={
          <EmptyState
            icon={Plane}
            title="No leave requests"
            description="No leave requests match the selected filter."
          />
        }
      />
    </div>
  );
}
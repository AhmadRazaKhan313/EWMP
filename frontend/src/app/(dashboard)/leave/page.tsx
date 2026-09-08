"use client";

import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Plane, Check, X, Filter, Plus } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Button, EmptyState, PageHeader } from "@/components/atoms";
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

  const { data, isLoading } = useQuery({
    queryKey: ["leave-requests", statusFilter],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: LeaveRequest[]; total: number }>(
        "/leave/requests",
        { params: { status: statusFilter || undefined } },
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

  const columns: ColumnDef<LeaveRequest, unknown>[] = [
    {
      header: "Employee",
      accessorKey: "employee_name",
      cell: ({ getValue }) => (
        <span className="font-medium">{getValue<string>()}</span>
      ),
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
        if (req.status !== "pending") return null;
        return (
          <div className="flex items-center gap-1.5">
            <button
              onClick={(e) => { e.stopPropagation(); approveMutation.mutate(req.id); }}
              className="flex h-7 w-7 items-center justify-center rounded-md bg-[hsl(var(--success-subtle))] text-[hsl(var(--success))] hover:opacity-80"
              title="Approve"
            >
              <Check size={13} />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); rejectMutation.mutate(req.id); }}
              className="flex h-7 w-7 items-center justify-center rounded-md bg-[hsl(var(--status-error-bg))] text-[hsl(var(--destructive))] hover:opacity-80"
              title="Reject"
            >
              <X size={13} />
            </button>
          </div>
        );
      },
      size: 80,
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
            {pending > 0 && (
              <span className="rounded-full bg-[hsl(var(--warning-subtle))] px-2.5 py-1 text-xs font-semibold text-[hsl(var(--warning))]">
                {pending} pending
              </span>
            )}
            <Button variant="outline" icon={<Filter size={14} />}>Filter</Button>
            <Button icon={<Plus size={14} />} onClick={() => setApplyOpen(true)}>Apply for Leave</Button>
          </div>
        }
      />

      <ApplyLeaveModal open={applyOpen} onClose={() => setApplyOpen(false)} />

      {/* Status filter tabs */}
      <div className="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-1 w-fit">
        {["", "pending", "approved", "rejected"].map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              statusFilter === s
                ? "bg-[hsl(var(--background))] shadow-[var(--shadow-xs)] text-[hsl(var(--foreground))]"
                : "text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
            }`}
          >
            {s === "" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

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
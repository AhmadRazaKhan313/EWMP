"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { ColumnDef } from "@tanstack/react-table";
import { Monitor, Wifi, WifiOff, UserX, ShieldAlert, Lock, RotateCcw, Power } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { AvatarLabelGroup, Button, Card, EmptyState, PageHeader, StatusDot } from "@/components/atoms";
import type { Device } from "@/types";

const statusDotColor: Record<string, "green" | "red" | "yellow" | "gray"> = {
  online:          "green",
  offline:         "red",
  idle:            "yellow",
  locked:          "yellow",
  sleeping:        "gray",
  decommissioned:  "gray",
};

function lastSeen(v: string | null): string {
  if (!v) return "Never";
  const diff = Math.floor((Date.now() - new Date(v).getTime()) / 1000);
  return diff < 60 ? `${diff}s ago` : diff < 3600 ? `${Math.floor(diff / 60)}m ago` : diff < 86400 ? `${Math.floor(diff / 3600)}h ago` : `${Math.floor(diff / 86400)}d ago`;
}

type BulkAction = "lock" | "restart" | "shutdown";
const BULK_LABEL: Record<BulkAction, string> = { lock: "Lock", restart: "Restart", shutdown: "Shut down" };

export default function DevicesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<BulkAction | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["devices"],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: Device[]; total: number }>("/devices", {
        params: { page_size: 200 },
      });
      return data;
    },
    refetchInterval: 30_000, // Live refresh every 30s
  });

  // Old links /devices?device_id=…&tab=alerts (alerts page, notification bell) -> the device page.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const id = q.get("device_id");
    if (id) router.replace(`/devices/${id}${q.get("tab") ? `?tab=${q.get("tab")}` : ""}`);
  }, [router]);

  const devices = useMemo(() => data?.items ?? [], [data]);
  const online     = devices.filter((d) => d.status === "online").length;
  const offline    = devices.filter((d) => d.status !== "online").length;
  const unassigned = devices.filter((d) => !d.assigned_employee).length;

  function toggle(id: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  const allChecked = devices.length > 0 && devices.every((d) => checked.has(d.id));

  async function runBulk(action: BulkAction) {
    const ids = devices.filter((d) => checked.has(d.id)).map((d) => d.id);
    if (ids.length === 0) return;
    const label = BULK_LABEL[action];
    const who = ids.length === 1 ? "this employee's computer" : `${ids.length} computers`;
    if (!window.confirm(`${label} ${who}? It will apply on each computer's next check-in (within ~60s).`)) return;
    setBusy(action);
    const results = await Promise.allSettled(ids.map((id) => apiClient.post(`/devices/${id}/actions/${action}`)));
    setBusy(null);
    const ok = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.length - ok;
    if (ok) toast.success(`${label} queued for ${ok} computer${ok === 1 ? "" : "s"}`);
    if (failed) toast.error(`${failed} could not be queued — check your permissions`);
    setChecked(new Set());
    void queryClient.invalidateQueries({ queryKey: ["devices"] });
  }

  const columns = useMemo<ColumnDef<Device, unknown>[]>(
    () => [
      {
        id: "select",
        header: () => (
          <input
            type="checkbox"
            aria-label="Select all"
            checked={allChecked}
            onChange={() => setChecked(allChecked ? new Set() : new Set(devices.map((d) => d.id)))}
          />
        ),
        cell: ({ row }) => (
          <span onClick={(e) => e.stopPropagation()}>
            <input
              type="checkbox"
              aria-label={`Select ${row.original.assigned_employee?.full_name ?? row.original.hostname}`}
              checked={checked.has(row.original.id)}
              onChange={() => toggle(row.original.id)}
            />
          </span>
        ),
        enableSorting: false,
        size: 40,
      },
      {
        header: "Employee",
        accessorFn: (r) =>
          [r.assigned_employee?.full_name, r.assigned_employee?.employee_code, r.assigned_employee?.department, r.hostname]
            .filter(Boolean)
            .join(" "),
        cell: ({ row }) => {
          const d = row.original;
          const e = d.assigned_employee;
          return e ? (
            <AvatarLabelGroup
              name={e.full_name ?? e.employee_code}
              subtext={e.employee_code}
              src={e.avatar_url}
              size="sm"
            />
          ) : (
            <div>
              <p className="text-sm font-medium text-[hsl(var(--foreground-muted))]">Unassigned</p>
              <p className="font-mono text-[11px] text-[hsl(var(--foreground-muted))]">{d.hostname}</p>
            </div>
          );
        },
        size: 240,
      },
      {
        header: "Department",
        accessorFn: (r) => r.assigned_employee?.department ?? "",
        cell: ({ getValue }) => <span className="text-sm">{getValue<string>() || "—"}</span>,
      },
      {
        header: "Designation",
        accessorFn: (r) => r.assigned_employee?.designation ?? "",
        cell: ({ getValue }) => <span className="text-sm">{getValue<string>() || "—"}</span>,
      },
      {
        header: "Status",
        accessorKey: "status",
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <StatusDot color={statusDotColor[row.original.status] ?? "gray"} pulse={row.original.status === "online"} />
            <span className="text-sm capitalize">{row.original.status}</span>
          </div>
        ),
      },
      {
        header: "Last Seen",
        accessorKey: "last_seen_at",
        cell: ({ getValue }) => <span className="text-xs text-[hsl(var(--foreground-subtle))]">{lastSeen(getValue<string | null>())}</span>,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [checked, allChecked, devices],
  );

  const n = checked.size;
  const count = n > 0 ? ` (${n})` : "";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Device Management"
        description="Lock, restart or shut down your team's computers. Tick the employees, then use the buttons."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" icon={<Lock size={15} />} disabled={n === 0 || busy !== null} onClick={() => runBulk("lock")}>
              Lock{count}
            </Button>
            <Button variant="secondary" icon={<RotateCcw size={15} />} disabled={n === 0 || busy !== null} onClick={() => runBulk("restart")}>
              Restart{count}
            </Button>
            <Button variant="destructive" icon={<Power size={15} />} disabled={n === 0 || busy !== null} onClick={() => runBulk("shutdown")}>
              Shutdown{count}
            </Button>
            <span className="mx-1 hidden h-6 w-px bg-[hsl(var(--border))] sm:block" />
            <Button variant="secondary" icon={<ShieldAlert size={15} />} onClick={() => router.push("/devices/alerts")}>
              View Alerts
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-3 gap-4">
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]">
              <Wifi size={16} className="text-[hsl(var(--success))]" />
            </div>
            <div>
              <p className="text-2xl font-semibold font-heading">{online}</p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">Online</p>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--status-error-bg))]">
              <WifiOff size={16} className="text-[hsl(var(--destructive))]" />
            </div>
            <div>
              <p className="text-2xl font-semibold font-heading">{offline}</p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">Offline</p>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--warning-subtle))]">
              <UserX size={16} className="text-[hsl(var(--warning))]" />
            </div>
            <div>
              <p className="text-2xl font-semibold font-heading">{unassigned}</p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">Not assigned to anyone</p>
            </div>
          </div>
        </Card>
      </div>

      {n > 0 && (
        <div className="flex items-center justify-between rounded-lg border border-[hsl(var(--brand-200))] bg-[hsl(var(--accent))] px-4 py-2 text-sm">
          <span>{n} selected</span>
          <button onClick={() => setChecked(new Set())} className="text-xs font-semibold text-[hsl(var(--primary))] hover:underline">
            Clear selection
          </button>
        </div>
      )}

      <DataTable
        data={devices}
        columns={columns}
        isLoading={isLoading}
        searchPlaceholder="Search employee or department…"
        onRowClick={(row) => router.push(`/devices/${row.id}`)}
        emptyState={
          <EmptyState
            icon={Monitor}
            title="No computers yet"
            description="When an employee logs in to the desktop app, their computer appears here."
          />
        }
      />

    </div>
  );
}

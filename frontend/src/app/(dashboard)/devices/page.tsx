"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import type { ColumnDef } from "@tanstack/react-table";
import { Monitor, Wifi, WifiOff, Shield, AlertTriangle, Plus, Copy, Check, X, Loader2, ShieldAlert } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Button, Card, EmptyState, PageHeader, StatusDot } from "@/components/atoms";
import { DeviceDrawer } from "@/components/organisms/DeviceDrawer";
import type { Device } from "@/types";

// ── Enrollment modal ───────────────────────────────────────────────────────
// Fetches a real org-scoped enrollment token from the backend so an admin
// can actually set up the agent/ewmp_agent.py script on a machine, instead
// of the "Enroll Device" button just being decorative.
function EnrollDeviceModal({ onClose }: { onClose: () => void }) {
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    apiClient
      .get<{ enrollment_token: string }>("/devices/enrollment-token")
      .then(({ data }) => setToken(data.enrollment_token))
      .catch(() => toast.error("Couldn't generate an enrollment token — check your permissions."))
      .finally(() => setLoading(false));
  }, []);

  function copy() {
    if (!token) return;
    navigator.clipboard.writeText(token);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-heading text-base font-semibold">Enroll a Device</h3>
          <button onClick={onClose} className="text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={18} />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-[hsl(var(--foreground-muted))]">
            <Loader2 size={16} className="animate-spin" /> Generating enrollment token…
          </div>
        ) : token ? (
          <div className="space-y-3">
            <p className="text-sm text-[hsl(var(--foreground-muted))]">
              Copy this token, then on the target machine run the desktop agent
              (see <code className="text-xs">agent/README.md</code>):
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 truncate rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--secondary))] px-3 py-2 text-xs">
                {token}
              </code>
              <button
                onClick={copy}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-[hsl(var(--border))] hover:bg-[hsl(var(--accent))]"
              >
                {copied ? <Check size={14} className="text-[hsl(var(--success))]" /> : <Copy size={14} />}
              </button>
            </div>
            <pre className="overflow-x-auto rounded-md bg-[hsl(var(--secondary))] p-3 text-xs">
{`python ewmp_agent.py --server ${typeof window !== "undefined" ? window.location.origin.replace("3000", "8000") : "http://localhost:8000"} \\
  --enroll-token ${token.slice(0, 16)}...`}
            </pre>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">
              This token is valid for a year and works for any number of machines in your organization.
            </p>
          </div>
        ) : (
          <p className="text-sm text-[hsl(var(--destructive))]">Failed to generate a token. Check your permissions.</p>
        )}
      </div>
    </div>
  );
}

function HealthBar({ score }: { score: number | null }) {
  if (score === null) return <span className="text-[hsl(var(--foreground-muted))]">—</span>;
  const color = score >= 80 ? "bg-[hsl(var(--success))]" : score >= 50 ? "bg-[hsl(var(--warning))]" : "bg-[hsl(var(--destructive))]";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-[hsl(var(--secondary))]">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="font-mono text-xs text-[hsl(var(--foreground-subtle))]">{score}</span>
    </div>
  );
}

function MetricBar({ value, label }: { value: number | null; label: string }) {
  if (value === null) return <span className="text-[hsl(var(--foreground-muted))]">—</span>;
  const color = value > 90 ? "bg-[hsl(var(--destructive))]" : value > 70 ? "bg-[hsl(var(--warning))]" : "bg-[hsl(var(--success))]";
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-[hsl(var(--secondary))]">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="font-mono text-xs">{value}%</span>
    </div>
  );
}

const statusDotColor: Record<string, "green" | "red" | "yellow" | "gray"> = {
  online:          "green",
  offline:         "red",
  idle:            "yellow",
  locked:          "yellow",
  sleeping:        "gray",
  decommissioned:  "gray",
};

const columns: ColumnDef<Device, unknown>[] = [
  {
    header: "Device",
    accessorFn: (r) => r.hostname,
    cell: ({ row }) => {
      const d = row.original;
      return (
        <div>
          <div className="flex items-center gap-2">
            <StatusDot color={statusDotColor[d.status] ?? "gray"} pulse={d.status === "online"} />
            <span className="font-medium">{d.device_name ?? d.hostname}</span>
          </div>
          <p className="ml-4 font-mono text-[11px] text-[hsl(var(--foreground-muted))]">{d.hostname}</p>
        </div>
      );
    },
    size: 200,
  },
  {
    header: "OS",
    accessorKey: "os_name",
    cell: ({ row }) => (
      <div>
        <p className="text-sm capitalize">{row.original.os_type}</p>
        <p className="text-xs text-[hsl(var(--foreground-muted))]">{row.original.os_version}</p>
      </div>
    ),
  },
  {
    header: "Health",
    accessorKey: "health_score",
    cell: ({ getValue }) => <HealthBar score={getValue<number | null>()} />,
  },
  {
    header: "CPU",
    accessorKey: "cpu_usage_percent",
    cell: ({ getValue }) => <MetricBar value={getValue<number | null>()} label="CPU" />,
  },
  {
    header: "RAM",
    accessorKey: "ram_usage_percent",
    cell: ({ getValue }) => <MetricBar value={getValue<number | null>()} label="RAM" />,
  },
  {
    header: "IP",
    accessorKey: "local_ip",
    cell: ({ row }) => (
      <div className="font-mono text-xs text-[hsl(var(--foreground-subtle))]">
        <div>{row.original.local_ip ?? "—"}</div>
        <div className="text-[hsl(var(--foreground-muted))]">{row.original.public_ip ?? ""}</div>
      </div>
    ),
  },
  {
    header: "Last Seen",
    accessorKey: "last_seen_at",
    cell: ({ getValue }) => {
      const v = getValue<string | null>();
      if (!v) return <span className="text-[hsl(var(--foreground-muted))]">Never</span>;
      const diff = Math.floor((Date.now() - new Date(v).getTime()) / 1000);
      const label = diff < 60 ? `${diff}s ago` : diff < 3600 ? `${Math.floor(diff / 60)}m ago` : diff < 86400 ? `${Math.floor(diff / 3600)}h ago` : `${Math.floor(diff / 86400)}d ago`;
      return <span className="text-xs text-[hsl(var(--foreground-subtle))]">{label}</span>;
    },
  },
];

export default function DevicesPage() {
  const router = useRouter();
  const [showEnroll, setShowEnroll] = useState(false);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["devices"],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: Device[]; total: number }>("/devices");
      return data;
    },
    refetchInterval: 30_000, // Live refresh every 30s
  });

  const devices = data?.items ?? [];
  const online  = devices.filter((d) => d.status === "online").length;
  const offline = devices.filter((d) => d.status === "offline").length;
  const alerts  = devices.filter((d) => (d.health_score ?? 100) < 50).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Device Management"
        description="Monitor and manage your entire device fleet in real time."
        action={
          <div className="flex gap-2">
            <Button
              variant="secondary"
              icon={<ShieldAlert size={15} />}
              onClick={() => router.push("/devices/alerts")}
            >
              View Alerts
            </Button>
            <Button icon={<Plus size={15} />} onClick={() => setShowEnroll(true)}>Enroll Device</Button>
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
              <AlertTriangle size={16} className="text-[hsl(var(--warning))]" />
            </div>
            <div>
              <p className="text-2xl font-semibold font-heading">{alerts}</p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">Health Alerts</p>
            </div>
          </div>
        </Card>
      </div>

      <DataTable
        data={devices}
        columns={columns}
        isLoading={isLoading}
        searchPlaceholder="Search by hostname or IP…"
        onRowClick={(row) => setSelectedDeviceId(row.id)}
        emptyState={
          <EmptyState
            icon={Monitor}
            title="No devices enrolled"
            description="Install the EWMP desktop agent on employee machines to start monitoring."
            action={<Button icon={<Plus size={14} />} onClick={() => setShowEnroll(true)}>Enroll First Device</Button>}
          />
        }
      />

      {showEnroll && <EnrollDeviceModal onClose={() => setShowEnroll(false)} />}
      {selectedDeviceId && (
        <DeviceDrawer deviceId={selectedDeviceId} onClose={() => setSelectedDeviceId(null)} />
      )}
    </div>
  );
}

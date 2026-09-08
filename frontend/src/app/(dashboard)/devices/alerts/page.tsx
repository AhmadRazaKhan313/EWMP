"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldAlert, Check, CheckCheck, Filter, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";
import { useAlertsInbox, useAcknowledgeAlert, useBulkAcknowledgeAlerts } from "@/services/devices.service";

function fmtDate(iso: string) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function DeviceAlertsInboxPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [alertType, setAlertType] = useState<"" | "flagged_app_usage" | "flagged_browsing">("");
  const [statusFilter, setStatusFilter] = useState<"" | "unacknowledged" | "acknowledged">("unacknowledged");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data, isLoading } = useAlertsInbox({
    page,
    page_size: 50,
    alert_type: alertType || undefined,
    is_acknowledged: statusFilter === "" ? undefined : statusFilter === "acknowledged",
  });

  const bulkAckMutation = useBulkAcknowledgeAlerts();

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (!data) return;
    const allIds = data.items.map((a) => a.id);
    const allSelected = allIds.every((id) => selected.has(id));
    setSelected(allSelected ? new Set() : new Set(allIds));
  }

  async function acknowledgeSelected() {
    if (selected.size === 0) return;
    try {
      const result = await bulkAckMutation.mutateAsync(Array.from(selected));
      toast.success(`${result.acknowledged} alert(s) acknowledged`);
      setSelected(new Set());
    } catch {
      toast.error("Couldn't acknowledge — check your permissions");
    }
  }

  const items = data?.items ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Device Alerts"
        description={
          data
            ? `${data.unacknowledged_count} unacknowledged in the last 7 days across your fleet`
            : "Flagged activity across every enrolled device"
        }
      />

      {/* Filters */}
      <Card padding={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-[hsl(var(--border))] px-4 py-3">
          <Filter size={14} className="text-[hsl(var(--foreground-muted))]" />
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value as typeof statusFilter); setPage(1); }}
            className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1.5 text-xs"
          >
            <option value="unacknowledged">Unacknowledged</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="">All statuses</option>
          </select>
          <select
            value={alertType}
            onChange={(e) => { setAlertType(e.target.value as typeof alertType); setPage(1); }}
            className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1.5 text-xs"
          >
            <option value="">All types</option>
            <option value="flagged_app_usage">App usage</option>
            <option value="flagged_browsing">Browsing</option>
          </select>

          {selected.size > 0 && (
            <div className="ml-auto flex items-center gap-2">
              <span className="text-xs text-[hsl(var(--foreground-muted))]">{selected.size} selected</span>
              <Button
                size="sm"
                variant="secondary"
                icon={<CheckCheck size={13} />}
                onClick={acknowledgeSelected}
                disabled={bulkAckMutation.isPending}
              >
                Acknowledge Selected
              </Button>
            </div>
          )}
        </div>

        {isLoading ? (
          <div className="flex justify-center py-16">
            <Loader2 size={20} className="animate-spin text-[hsl(var(--foreground-muted))]" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={ShieldAlert}
            title="No alerts"
            description={
              statusFilter === "unacknowledged"
                ? "Nothing unacknowledged right now — your fleet is quiet."
                : "No alerts match these filters."
            }
          />
        ) : (
          <>
            <div className="flex items-center gap-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] px-4 py-2 text-xs font-medium text-[hsl(var(--foreground-muted))]">
              <input
                type="checkbox"
                checked={items.length > 0 && items.every((a) => selected.has(a.id))}
                onChange={toggleSelectAll}
              />
              <span className="flex-1">DEVICE</span>
              <span className="w-24">TYPE</span>
              <span className="flex-[2]">DETAIL</span>
              <span className="w-20">WHEN</span>
              <span className="w-8" />
            </div>
            <div>
              {items.map((a) => (
                <AlertRow
                  key={a.id}
                  alert={a}
                  isSelected={selected.has(a.id)}
                  onToggleSelect={() => toggleSelected(a.id)}
                  onViewDevice={() => router.push(`/devices?device_id=${a.device_id}&tab=alerts`)}
                />
              ))}
            </div>
          </>
        )}

        {/* Pagination */}
        {data && data.total_pages > 1 && (
          <div className="flex items-center justify-between border-t border-[hsl(var(--border))] px-4 py-3">
            <span className="text-xs text-[hsl(var(--foreground-muted))]">
              Page {data.page} of {data.total_pages} · {data.total} total
            </span>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={page >= data.total_pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function AlertRow({
  alert, isSelected, onToggleSelect, onViewDevice,
}: {
  alert: { id: string; device_id: string; device_name: string; alert_type: string; matched_term: string; detail: string; occurred_at: string; is_acknowledged: boolean };
  isSelected: boolean;
  onToggleSelect: () => void;
  onViewDevice: () => void;
}) {
  const acknowledgeMutation = useAcknowledgeAlert(alert.device_id);

  async function handleAcknowledge() {
    try {
      await acknowledgeMutation.mutateAsync(alert.id);
    } catch {
      toast.error("Couldn't acknowledge");
    }
  }

  return (
    <div
      className={`flex items-center gap-3 border-b border-[hsl(var(--border))] px-4 py-2.5 text-sm last:border-0 hover:bg-[hsl(var(--accent))] ${
        alert.is_acknowledged ? "opacity-60" : ""
      }`}
    >
      <input type="checkbox" checked={isSelected} onChange={onToggleSelect} />
      <button onClick={onViewDevice} className="flex-1 truncate text-left font-medium hover:underline">
        {alert.device_name}
      </button>
      <span className="w-24">
        <Badge variant={alert.alert_type === "flagged_browsing" ? "warning" : "outline"}>
          {alert.alert_type === "flagged_browsing" ? "Browsing" : "App"}
        </Badge>
      </span>
      <span className="flex-[2] truncate text-xs text-[hsl(var(--foreground-muted))]">
        {alert.detail} <span className="text-[hsl(var(--foreground-muted))]">(matched: {alert.matched_term})</span>
      </span>
      <span className="w-20 shrink-0 text-xs text-[hsl(var(--foreground-muted))]">{fmtDate(alert.occurred_at)}</span>
      <span className="w-8 shrink-0">
        {!alert.is_acknowledged && (
          <button
            onClick={handleAcknowledge}
            disabled={acknowledgeMutation.isPending}
            title="Acknowledge"
            className="flex h-6 w-6 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))]"
          >
            <Check size={13} />
          </button>
        )}
      </span>
    </div>
  );
}

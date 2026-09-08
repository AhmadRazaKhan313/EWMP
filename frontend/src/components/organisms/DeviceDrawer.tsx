"use client";

import { useState } from "react";
import { X, Monitor, Cpu, HardDrive, Wifi, User, AlertTriangle, Lock, RotateCcw,
  Power, MessageSquare, Trash2, Loader2, Activity, Camera, RefreshCw, ShieldAlert, Check, ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/atoms";
import { useEmployees } from "@/services/employee.service";
import {
  useDevice, useDeviceMetrics, useDeviceProcesses, useAssignDevice, useUnassignDevice,
  useDeviceAction, useMessageDevice, useDecommissionDevice,
  useDeviceScreenshots, useRequestScreenshot, useScreenshotImage,
  useDeviceAlerts, useAcknowledgeAlert,
  useAllowedApps, useAddAllowedApp, useRemoveAllowedApp, useActivityWatchlist,
} from "@/services/devices.service";
import type { DeviceScreenshotItem, AllowedAppItem } from "@/types";

function fmtBytes(gb: number | null) {
  if (gb === null) return "—";
  return `${gb.toFixed(1)} GB`;
}

function fmtDate(iso: string | null) {
  if (!iso) return "Never";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function StatRow({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm">
      <span className="text-[hsl(var(--foreground-muted))]">{label}</span>
      <span className="font-medium text-[hsl(var(--foreground))]">{value ?? "—"}</span>
    </div>
  );
}

function MiniBar({ value }: { value: number | null }) {
  if (value === null) return <span className="text-xs text-[hsl(var(--foreground-muted))]">—</span>;
  const color = value > 90 ? "bg-[hsl(var(--destructive))]" : value > 70 ? "bg-[hsl(var(--warning))]" : "bg-[hsl(var(--success))]";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-[hsl(var(--secondary))]">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="font-mono text-xs">{value.toFixed(0)}%</span>
    </div>
  );
}

export function DeviceDrawer({ deviceId, onClose }: { deviceId: string; onClose: () => void }) {
  const [tab, setTab] = useState<"overview" | "metrics" | "processes" | "screen" | "alerts" | "allowed">("overview");
  const [showAssign, setShowAssign] = useState(false);
  const [showMessage, setShowMessage] = useState(false);
  const [messageText, setMessageText] = useState("");

  const { data: device, isLoading } = useDevice(deviceId);
  const { data: metrics } = useDeviceMetrics(deviceId, 24, tab === "metrics");
  const { data: processData } = useDeviceProcesses(deviceId, tab === "processes");
  const { data: screenshots } = useDeviceScreenshots(deviceId, tab === "screen");
  const requestScreenshotMutation = useRequestScreenshot(deviceId);
  const [selectedScreenshot, setSelectedScreenshot] = useState<DeviceScreenshotItem | null>(null);
  const { data: alerts } = useDeviceAlerts(deviceId, tab === "alerts");
  const acknowledgeMutation = useAcknowledgeAlert(deviceId);
  const { data: allowedApps } = useAllowedApps(deviceId, tab === "allowed");
  const { data: watchlist } = useActivityWatchlist();
  const addAllowedMutation = useAddAllowedApp(deviceId);
  const removeAllowedMutation = useRemoveAllowedApp(deviceId);

  const assignMutation = useAssignDevice(deviceId);
  const unassignMutation = useUnassignDevice(deviceId);
  const actionMutation = useDeviceAction(deviceId);
  const messageMutation = useMessageDevice(deviceId);
  const decommissionMutation = useDecommissionDevice(deviceId);

  const { data: employeesData } = useEmployees({ page_size: 100 });

  async function runAction(action: "lock" | "restart" | "shutdown", label: string) {
    if (!window.confirm(`${label} this device? It will apply on the device's next check-in (within ~60s).`)) return;
    try {
      await actionMutation.mutateAsync(action);
      toast.success(`${label} command queued`);
    } catch {
      toast.error(`Couldn't queue ${label.toLowerCase()}`);
    }
  }

  async function requestScreenshot() {
    try {
      await requestScreenshotMutation.mutateAsync();
      toast.success("Screenshot requested — it'll appear here within about a minute");
    } catch {
      toast.error("Couldn't request a screenshot — check your permissions");
    }
  }

  async function sendMessage() {
    if (!messageText.trim()) return;
    try {
      await messageMutation.mutateAsync(messageText);
      toast.success("Message queued for the device");
      setMessageText("");
      setShowMessage(false);
    } catch {
      toast.error("Couldn't send message — check your permissions");
    }
  }

  async function decommission() {
    if (!window.confirm("Decommission this device? This revokes its agent token and removes it from the active fleet. This can't be undone.")) return;
    try {
      await decommissionMutation.mutateAsync();
      toast.success("Device decommissioned");
      onClose();
    } catch {
      toast.error("Couldn't decommission — check your permissions");
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]">
              <Monitor size={16} className="text-[hsl(var(--foreground-subtle))]" />
            </div>
            <div>
              <h2 className="font-heading text-sm font-semibold">{device?.device_name ?? device?.hostname ?? "Device"}</h2>
              <p className="font-mono text-[11px] text-[hsl(var(--foreground-muted))]">{device?.hostname}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={18} />
          </button>
        </div>

        {isLoading || !device ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 size={20} className="animate-spin text-[hsl(var(--foreground-muted))]" />
          </div>
        ) : (
          <>
            {/* Tabs */}
            <div className="flex gap-1 border-b border-[hsl(var(--border))] px-6">
              {(["overview", "metrics", "screen", "alerts", "allowed", "processes"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`border-b-2 px-3 py-2.5 text-xs font-medium capitalize transition-colors ${
                    tab === t
                      ? "border-[hsl(var(--primary))] text-[hsl(var(--primary))]"
                      : "border-transparent text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-4">
              {tab === "overview" && (
                <div className="space-y-5">
                  {/* Status + health */}
                  <div className="flex items-center gap-3">
                    <Badge variant={device.status === "online" ? "success" : device.status === "offline" ? "error" : "outline"}>
                      {device.status}
                    </Badge>
                    {device.health_score !== null && device.health_score < 70 && (
                      <Badge variant="warning"><AlertTriangle size={10} className="mr-1" />Health {device.health_score}</Badge>
                    )}
                    <span className="text-xs text-[hsl(var(--foreground-muted))]">Last seen {fmtDate(device.last_seen_at)}</span>
                  </div>

                  {device.health_issues.length > 0 && (
                    <div className="rounded-lg border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning-subtle))] p-3">
                      {device.health_issues.map((issue, i) => (
                        <p key={i} className="text-xs text-[hsl(var(--warning))]">⚠ {issue}</p>
                      ))}
                    </div>
                  )}

                  {/* Live metrics */}
                  {device.latest_metric && (
                    <div className="rounded-lg border border-[hsl(var(--border))] p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-[hsl(var(--foreground-muted))]">CPU</span>
                        <MiniBar value={device.latest_metric.cpu_usage_percent} />
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-[hsl(var(--foreground-muted))]">RAM</span>
                        <MiniBar value={device.latest_metric.ram_usage_percent} />
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-[hsl(var(--foreground-muted))]">Disk</span>
                        <MiniBar value={device.latest_metric.disk_usage_percent} />
                      </div>
                      {device.latest_metric.battery_percent !== null && (
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-[hsl(var(--foreground-muted))]">Battery</span>
                          <span className="text-xs font-mono">
                            {device.latest_metric.battery_percent}%
                            {device.latest_metric.battery_is_charging ? " ⚡" : ""}
                          </span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Assigned employee */}
                  <div>
                    <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-[hsl(var(--foreground-muted))]">
                      <User size={12} /> ASSIGNED TO
                    </h4>
                    {device.assigned_employee ? (
                      <div className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] p-3">
                        <div>
                          <p className="text-sm font-medium">{device.assigned_employee.full_name}</p>
                          <p className="text-xs text-[hsl(var(--foreground-muted))]">{device.assigned_employee.employee_code}</p>
                        </div>
                        <button
                          onClick={() => unassignMutation.mutate()}
                          disabled={unassignMutation.isPending}
                          className="text-xs text-[hsl(var(--destructive))] hover:underline"
                        >
                          Unassign
                        </button>
                      </div>
                    ) : showAssign ? (
                      <div className="space-y-2">
                        <select
                          className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm"
                          onChange={async (e) => {
                            if (!e.target.value) return;
                            try {
                              await assignMutation.mutateAsync(e.target.value);
                              toast.success("Device assigned");
                              setShowAssign(false);
                            } catch {
                              toast.error("Couldn't assign device");
                            }
                          }}
                          defaultValue=""
                        >
                          <option value="" disabled>Select an employee…</option>
                          {employeesData?.items.map((emp) => (
                            <option key={emp.id} value={emp.id}>{emp.full_name} ({emp.employee_code})</option>
                          ))}
                        </select>
                      </div>
                    ) : (
                      <button
                        onClick={() => setShowAssign(true)}
                        className="w-full rounded-lg border border-dashed border-[hsl(var(--border))] p-3 text-xs text-[hsl(var(--foreground-muted))] hover:border-[hsl(var(--primary))] hover:text-[hsl(var(--primary))]"
                      >
                        + Assign to an employee
                      </button>
                    )}
                  </div>

                  {/* Hardware */}
                  <div>
                    <h4 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-[hsl(var(--foreground-muted))]">
                      <Cpu size={12} /> HARDWARE
                    </h4>
                    <StatRow label="OS" value={`${device.os_name ?? device.os_type} ${device.os_version ?? ""}`} />
                    <StatRow label="CPU" value={device.cpu_model ? `${device.cpu_model} (${device.cpu_cores ?? "?"} cores)` : null} />
                    <StatRow label="RAM" value={fmtBytes(device.ram_total_gb)} />
                    <StatRow label="Disk" value={fmtBytes(device.disk_total_gb)} />
                    <StatRow label="GPU" value={device.gpu_model} />
                  </div>

                  {/* Network */}
                  <div>
                    <h4 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-[hsl(var(--foreground-muted))]">
                      <Wifi size={12} /> NETWORK
                    </h4>
                    <StatRow label="Local IP" value={device.local_ip} />
                    <StatRow label="Public IP" value={device.public_ip} />
                    <StatRow label="MAC" value={device.mac_address} />
                  </div>

                  {/* Identity */}
                  <div>
                    <h4 className="mb-1 text-xs font-semibold text-[hsl(var(--foreground-muted))]">IDENTITY</h4>
                    <StatRow label="Serial Number" value={device.serial_number} />
                    <StatRow label="Asset Tag" value={device.asset_tag} />
                    <StatRow label="Agent Version" value={device.agent_version} />
                  </div>
                </div>
              )}

              {tab === "metrics" && (
                <div className="space-y-3">
                  {!metrics || metrics.length === 0 ? (
                    <p className="py-8 text-center text-xs text-[hsl(var(--foreground-muted))]">
                      No metrics yet — the agent reports every heartbeat interval.
                    </p>
                  ) : (
                    <div className="space-y-1.5">
                      <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-[hsl(var(--foreground-muted))]">
                        <Activity size={12} /> LAST 24 HOURS ({metrics.length} points)
                      </p>
                      {metrics.slice(-20).reverse().map((m, i) => (
                        <div key={i} className="flex items-center justify-between border-b border-[hsl(var(--border))] py-1.5 text-xs">
                          <span className="text-[hsl(var(--foreground-muted))]">{new Date(m.recorded_at).toLocaleTimeString()}</span>
                          <div className="flex gap-3 font-mono">
                            <span>CPU {m.cpu_usage_percent?.toFixed(0) ?? "—"}%</span>
                            <span>RAM {m.ram_usage_percent?.toFixed(0) ?? "—"}%</span>
                            <span>Disk {m.disk_usage_percent?.toFixed(0) ?? "—"}%</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {tab === "processes" && (
                <div className="space-y-1.5">
                  {!processData || processData.processes.length === 0 ? (
                    <p className="py-8 text-center text-xs text-[hsl(var(--foreground-muted))]">
                      No process snapshot available yet.
                    </p>
                  ) : (
                    <>
                      <p className="mb-2 text-xs text-[hsl(var(--foreground-muted))]">
                        Captured {fmtDate(processData.captured_at)} — top by memory usage
                      </p>
                      {processData.processes.map((p) => (
                        <div key={p.pid} className="flex items-center justify-between border-b border-[hsl(var(--border))] py-1.5 text-xs">
                          <span className="truncate">{p.name} <span className="text-[hsl(var(--foreground-muted))]">#{p.pid}</span></span>
                          <span className="font-mono">{p.memory_percent}% mem</span>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}

              {tab === "screen" && (
                <ScreenTab
                  deviceId={deviceId}
                  screenshots={screenshots ?? []}
                  selected={selectedScreenshot}
                  onSelect={setSelectedScreenshot}
                  onRequest={requestScreenshot}
                  isRequesting={requestScreenshotMutation.isPending}
                />
              )}

              {tab === "alerts" && (
                <div className="space-y-3">
                  <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-3 text-xs text-[hsl(var(--foreground-muted))]">
                    <ShieldAlert size={13} className="mt-0.5 shrink-0" />
                    Only flagged matches against the organization's watch-list are shown here —
                    never a full browsing or activity history.
                  </div>
                  {!alerts || alerts.length === 0 ? (
                    <p className="py-8 text-center text-xs text-[hsl(var(--foreground-muted))]">
                      No flagged activity for this device.
                    </p>
                  ) : (
                    alerts.map((a) => (
                      <div
                        key={a.id}
                        className={`flex items-start justify-between gap-3 rounded-lg border p-3 ${
                          a.is_acknowledged
                            ? "border-[hsl(var(--border))] opacity-60"
                            : "border-[hsl(var(--warning))]/40 bg-[hsl(var(--warning-subtle))]"
                        }`}
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <Badge variant={a.alert_type === "flagged_browsing" ? "warning" : "outline"}>
                              {a.alert_type === "flagged_browsing" ? "Browsing" : "App Usage"}
                            </Badge>
                            <span className="text-xs text-[hsl(var(--foreground-muted))]">{fmtDate(a.occurred_at)}</span>
                          </div>
                          <p className="mt-1 truncate text-sm font-medium">{a.detail}</p>
                          <p className="text-xs text-[hsl(var(--foreground-muted))]">Matched: {a.matched_term}</p>
                        </div>
                        {!a.is_acknowledged && (
                          <button
                            onClick={() => acknowledgeMutation.mutate(a.id)}
                            title="Mark reviewed"
                            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))]"
                          >
                            <Check size={14} />
                          </button>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}

              {tab === "allowed" && (
                <AllowedAppsTab
                  watchlist={watchlist ?? []}
                  allowedApps={allowedApps ?? []}
                  onAllow={(domain) => addAllowedMutation.mutate({ domain_or_app: domain })}
                  onRevoke={(id) => removeAllowedMutation.mutate(id)}
                  isMutating={addAllowedMutation.isPending || removeAllowedMutation.isPending}
                />
              )}
            </div>

            {/* Actions footer */}
            <div className="space-y-3 border-t border-[hsl(var(--border))] px-6 py-4">
              {showMessage && (
                <div className="flex gap-2">
                  <input
                    value={messageText}
                    onChange={(e) => setMessageText(e.target.value)}
                    placeholder="Message to show on screen…"
                    className="flex-1 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1.5 text-xs"
                  />
                  <button onClick={sendMessage} className="rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs text-[hsl(var(--primary-foreground))]">
                    Send
                  </button>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => runAction("lock", "Lock")}
                  className="flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--accent))]"
                >
                  <Lock size={12} /> Lock
                </button>
                <button
                  onClick={() => runAction("restart", "Restart")}
                  className="flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--accent))]"
                >
                  <RotateCcw size={12} /> Restart
                </button>
                <button
                  onClick={() => runAction("shutdown", "Shut down")}
                  className="flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--accent))]"
                >
                  <Power size={12} /> Shutdown
                </button>
                <button
                  onClick={() => setShowMessage((v) => !v)}
                  className="flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--accent))]"
                >
                  <MessageSquare size={12} /> Message
                </button>
                <button
                  onClick={decommission}
                  className="ml-auto flex items-center gap-1.5 rounded-md border border-[hsl(var(--destructive))]/30 px-3 py-1.5 text-xs font-medium text-[hsl(var(--destructive))] hover:bg-[hsl(var(--status-error-bg))]"
                >
                  <Trash2 size={12} /> Decommission
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}

// ── Screen Tab ─────────────────────────────────────────────────────────────
function ScreenTab({
  deviceId, screenshots, selected, onSelect, onRequest, isRequesting,
}: {
  deviceId: string;
  screenshots: DeviceScreenshotItem[];
  selected: DeviceScreenshotItem | null;
  onSelect: (s: DeviceScreenshotItem | null) => void;
  onRequest: () => void;
  isRequesting: boolean;
}) {
  const latest = screenshots[0] ?? null;
  const active = selected ?? latest;
  const { data: imageUrl, isLoading: isImageLoading } = useScreenshotImage(
    deviceId,
    active?.id ?? null,
  );

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-3 text-xs text-[hsl(var(--foreground-muted))]">
        <Camera size={13} className="mt-0.5 shrink-0" />
        On-demand only — no continuous recording. Each capture is a single point-in-time
        screenshot, timestamped and tied to whoever requested it.
      </div>

      <button
        onClick={onRequest}
        disabled={isRequesting}
        className="flex w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-3 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
      >
        {isRequesting ? <Loader2 size={14} className="animate-spin" /> : <Camera size={14} />}
        Capture Now
      </button>

      {screenshots.length === 0 ? (
        <p className="py-8 text-center text-xs text-[hsl(var(--foreground-muted))]">
          No screenshots yet — click "Capture Now" to request one. It'll show up here once the
          device checks in (usually within a minute).
        </p>
      ) : (
        <>
          <div className="overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--secondary))]">
            {isImageLoading ? (
              <div className="flex h-56 items-center justify-center">
                <Loader2 size={18} className="animate-spin text-[hsl(var(--foreground-muted))]" />
              </div>
            ) : imageUrl ? (
              // eslint-disable-next-line @next/next/no-img-element -- authenticated blob URL, next/image can't fetch it
              <img src={imageUrl} alt="Device screen capture" className="w-full" />
            ) : (
              <div className="flex h-56 items-center justify-center text-xs text-[hsl(var(--foreground-muted))]">
                Couldn't load this screenshot
              </div>
            )}
          </div>
          {active && (
            <p className="text-center text-xs text-[hsl(var(--foreground-muted))]">
              Captured {fmtDate(active.captured_at)}
              {active.width && active.height ? ` · ${active.width}×${active.height}` : ""}
            </p>
          )}

          {screenshots.length > 1 && (
            <div>
              <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-[hsl(var(--foreground-muted))]">
                <RefreshCw size={12} /> HISTORY
              </p>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {screenshots.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => onSelect(s)}
                    className={`shrink-0 rounded-md border px-2 py-1.5 text-[11px] whitespace-nowrap transition-colors ${
                      active?.id === s.id
                        ? "border-[hsl(var(--primary))] bg-[hsl(var(--accent))] text-[hsl(var(--primary))]"
                        : "border-[hsl(var(--border))] text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))]"
                    }`}
                  >
                    {fmtDate(s.captured_at)}
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Allowed Apps Tab ─────────────────────────────────────────────────────────
function AllowedAppsTab({
  watchlist, allowedApps, onAllow, onRevoke, isMutating,
}: {
  watchlist: string[];
  allowedApps: AllowedAppItem[];
  onAllow: (domain: string) => void;
  onRevoke: (allowedAppId: string) => void;
  isMutating: boolean;
}) {
  const allowedByDomain = new Map(allowedApps.map((a) => [a.domain_or_app, a]));

  function label(domain: string) {
    // "whatsapp.com" -> "Whatsapp" — good enough for a checkbox list
    // without maintaining a separate display-name map per entry.
    const base = domain.split(".")[0] ?? domain;
    return base.charAt(0).toUpperCase() + base.slice(1);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-3 text-xs text-[hsl(var(--foreground-muted))]">
        <ShieldCheck size={13} className="mt-0.5 shrink-0" />
        Allowing an app/site here stops alerts for it on <strong>this device only</strong> — every
        other device still gets flagged for it as normal.
      </div>

      <div className="space-y-1.5">
        {watchlist.length === 0 ? (
          <p className="py-8 text-center text-xs text-[hsl(var(--foreground-muted))]">
            No organization watch-list configured.
          </p>
        ) : (
          watchlist.map((domain) => {
            const entry = allowedByDomain.get(domain);
            const isAllowed = !!entry;
            return (
              <label
                key={domain}
                className="flex cursor-pointer items-center justify-between rounded-lg border border-[hsl(var(--border))] px-3 py-2.5"
              >
                <div className="flex items-center gap-2.5">
                  <input
                    type="checkbox"
                    checked={isAllowed}
                    disabled={isMutating}
                    onChange={() => (isAllowed ? onRevoke(entry!.id) : onAllow(domain))}
                  />
                  <span className="text-sm font-medium">{label(domain)}</span>
                  <span className="text-xs text-[hsl(var(--foreground-muted))]">{domain}</span>
                </div>
                {isAllowed && <Badge variant="success">Allowed here</Badge>}
              </label>
            );
          })
        )}
      </div>
    </div>
  );
}

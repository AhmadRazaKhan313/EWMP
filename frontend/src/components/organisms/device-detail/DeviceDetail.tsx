"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity, AlertTriangle, ArrowLeft, Camera, Cpu, HardDrive, LayoutDashboard, ListTree, Loader2, Lock, MemoryStick,
  MessageSquare, Monitor, Power, RotateCcw, ShieldAlert, ShieldCheck, Trash2, User, Wifi,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/utils/cn";
import { Badge, Button, EmptyState, PageHeader, Skeleton } from "@/components/atoms";
import { useEmployees } from "@/services/employee.service";
import {
  useAcknowledgeAlert, useActivityWatchlist, useAddAllowedApp, useAllowedApps, useAssignDevice, useDecommissionDevice,
  useDevice, useDeviceAction, useDeviceAlerts, useDeviceMetrics, useDeviceProcesses, useDeviceScreenshots,
  useMessageDevice, useRemoveAllowedApp, useRequestScreenshot, useUnassignDevice,
} from "@/services/devices.service";
import type { DeviceScreenshotItem } from "@/types";
import { fmtDate, fmtGb, TABS, type TabId } from "./format";
import { AllowedAppsTab, AlertsTab, MetricsTab, ProcessesTab, ScreenTab } from "./tabs";

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 text-sm">
      <dt className="text-[hsl(var(--foreground-muted))]">{label}</dt>
      <dd className="break-all text-right font-medium">{value || "—"}</dd>
    </div>
  );
}

function Section({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-[hsl(var(--border))]">
      <h3 className="flex items-center gap-2 border-b border-[hsl(var(--border))] px-4 py-3 text-sm font-semibold">
        <Icon size={14} aria-hidden /> {title}
      </h3>
      <dl className="divide-y divide-[hsl(var(--border))] px-4">{children}</dl>
    </section>
  );
}

const TAB_ICONS: Record<TabId, React.ElementType> = {
  overview: LayoutDashboard, metrics: Activity, screen: Camera, alerts: ShieldAlert, allowed: ShieldCheck, processes: ListTree,
};

function tone(v: number) {
  return v > 90
    ? { bar: "bg-[hsl(var(--destructive))]", text: "text-[hsl(var(--destructive))]", bg: "bg-[hsl(var(--status-error-bg))]" }
    : v > 70
      ? { bar: "bg-[hsl(var(--warning))]", text: "text-[hsl(var(--warning))]", bg: "bg-[hsl(var(--warning-subtle))]" }
      : { bar: "bg-[hsl(var(--success))]", text: "text-[hsl(var(--success))]", bg: "bg-[hsl(var(--success-subtle))]" };
}

function UsageTile({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: number | null }) {
  const t = value === null ? null : tone(value);
  return (
    <div className="rounded-xl border border-[hsl(var(--border))] p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-[hsl(var(--foreground-muted))]">{label}</span>
        <span className={cn("flex h-8 w-8 items-center justify-center rounded-lg", t?.bg ?? "bg-[hsl(var(--secondary))]")}>
          <Icon size={15} aria-hidden className={t?.text ?? "text-[hsl(var(--foreground-muted))]"} />
        </span>
      </div>
      <p className="mt-2 font-heading text-2xl font-semibold">{value === null ? "—" : `${value.toFixed(0)}%`}</p>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[hsl(var(--secondary))]">
        {value !== null && <div className={cn("h-full rounded-full transition-[width] duration-500", t?.bar)} style={{ width: `${Math.min(100, value)}%` }} />}
      </div>
    </div>
  );
}

const statusVariant = (s: string) => (s === "online" ? "success" : s === "offline" ? "error" : "outline") as "success" | "error" | "outline";

/** Full-page replacement for the old right-hand DeviceDrawer. Same data and actions, same hooks. */
export function DeviceDetail({ deviceId }: { deviceId: string }) {
  const router = useRouter();
  const [tab, setTab] = useState<TabId>("overview");
  const [showAssign, setShowAssign] = useState(false);
  const [showMessage, setShowMessage] = useState(false);
  const [messageText, setMessageText] = useState("");
  const [selectedShot, setSelectedShot] = useState<DeviceScreenshotItem | null>(null);

  const { data: device, isLoading, isError } = useDevice(deviceId);
  const { data: metrics } = useDeviceMetrics(deviceId, 24, tab === "metrics");
  const { data: processData } = useDeviceProcesses(deviceId, tab === "processes");
  const { data: screenshots } = useDeviceScreenshots(deviceId, tab === "screen");
  const { data: alerts } = useDeviceAlerts(deviceId, tab === "alerts");
  const { data: allowedApps } = useAllowedApps(deviceId, tab === "allowed");
  const { data: watchlist } = useActivityWatchlist();
  const { data: employeesData } = useEmployees({ page_size: 100 });

  const screenshotMut = useRequestScreenshot(deviceId);
  const acknowledgeMut = useAcknowledgeAlert(deviceId);
  const addAllowedMut = useAddAllowedApp(deviceId);
  const removeAllowedMut = useRemoveAllowedApp(deviceId);
  const assignMut = useAssignDevice(deviceId);
  const unassignMut = useUnassignDevice(deviceId);
  const actionMut = useDeviceAction(deviceId);
  const messageMut = useMessageDevice(deviceId);
  const decommissionMut = useDecommissionDevice(deviceId);

  async function runAction(action: "lock" | "restart" | "shutdown", label: string) {
    if (!window.confirm(`${label} this device? It will apply on the device's next check-in (within ~60s).`)) return;
    try { await actionMut.mutateAsync(action); toast.success(`${label} command queued`); }
    catch { toast.error(`Couldn't queue ${label.toLowerCase()}`); }
  }

  async function requestScreenshot() {
    try { await screenshotMut.mutateAsync(); toast.success("Screenshot requested — it'll appear here within about a minute"); }
    catch { toast.error("Couldn't request a screenshot — check your permissions"); }
  }

  async function sendMessage() {
    if (!messageText.trim()) return;
    try { await messageMut.mutateAsync(messageText); toast.success("Message queued for the device"); setMessageText(""); setShowMessage(false); }
    catch { toast.error("Couldn't send message — check your permissions"); }
  }

  async function decommission() {
    if (!window.confirm("Decommission this device? This revokes its agent token and removes it from the active fleet. This can't be undone.")) return;
    try { await decommissionMut.mutateAsync(); toast.success("Device decommissioned"); router.push("/devices"); }
    catch { toast.error("Couldn't decommission — check your permissions"); }
  }

  if (isError || (!isLoading && !device)) {
    return (
      <EmptyState icon={Monitor} title="Device not found"
        description="It may have been decommissioned, or you may not have access to it."
        action={<Button onClick={() => router.push("/devices")}>Back to devices</Button>} />
    );
  }

  const meta = TABS.find((t) => t.id === tab)!;
  const tabIndex = TABS.findIndex((t) => t.id === tab);
  const name = device?.device_name ?? device?.hostname ?? "Device";

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={
          <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-sm text-[hsl(var(--foreground-muted))]">
            <Link href="/devices" className="hover:text-[hsl(var(--foreground))]">Devices</Link>
            <span aria-hidden>/</span>
            <span aria-current="page" className="font-medium text-[hsl(var(--foreground-subtle))]">{name}</span>
          </nav>
        }
        title={name}
        description={device ? `${device.hostname} · last seen ${fmtDate(device.last_seen_at)}` : "Loading device…"}
        action={<Button variant="secondary" onClick={() => router.push("/devices")} icon={<ArrowLeft size={15} className="mr-1.5" />}>Back</Button>}
      />

      <div className="mx-auto max-w-6xl overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]">
        {/* Section stepper */}
        <nav aria-label="Device sections" className="border-b border-[hsl(var(--border))] px-5 py-5 sm:px-8">
          <ol className="flex items-start overflow-x-auto">
            {TABS.map((t, i) => {
              const active = t.id === tab;
              return (
                <li key={t.id} className="relative flex min-w-[84px] flex-1 flex-col items-center">
                  {i > 0 && (
                    <span aria-hidden className={cn("absolute right-1/2 top-[18px] h-0.5 w-full -translate-y-1/2",
                      i <= tabIndex ? "bg-[hsl(var(--brand-600))]" : "bg-[hsl(var(--border))]")} />
                  )}
                  <button type="button" onClick={() => setTab(t.id)} aria-current={active ? "step" : undefined}
                    aria-label={`${t.label} section`}
                    className={cn(
                      "relative z-10 flex h-9 w-9 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors",
                      "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[hsl(var(--brand-100))]",
                      active && "border-[hsl(var(--brand-600))] bg-[hsl(var(--brand-600))] text-white shadow-[0_0_0_4px_hsl(var(--brand-100))]",
                      !active && i < tabIndex && "border-[hsl(var(--brand-600))] bg-[hsl(var(--brand-600))] text-white",
                      !active && i > tabIndex && "border-[hsl(var(--brand-300))] bg-[hsl(var(--background))] text-[hsl(var(--brand-700))]",
                    )}>
                    {(() => { const Icon = TAB_ICONS[t.id]; return <Icon size={16} aria-hidden />; })()}
                  </button>
                  <span className={cn("mt-2 text-xs font-medium", active ? "text-[hsl(var(--brand-700))]" : "text-[hsl(var(--foreground-muted))]")}>{t.label}</span>
                </li>
              );
            })}
          </ol>
        </nav>

        <div className="grid grid-cols-1 gap-8 px-5 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_280px]">
          <section aria-labelledby="device-section-title" className="min-w-0">
            <h2 id="device-section-title" className="font-heading text-xl font-semibold">{meta.title}</h2>
            <p className="mb-6 mt-1 text-sm text-[hsl(var(--foreground-muted))]">{meta.subtitle}</p>

            {isLoading || !device ? (
              <div className="space-y-3"><Skeleton className="h-24 w-full" /><Skeleton className="h-40 w-full" /></div>
            ) : (
              <>
                {tab === "overview" && (
                  <div className="space-y-5">
                    {device.health_issues.length > 0 && (
                      <div className="rounded-xl border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning-subtle))] p-3">
                        {device.health_issues.map((issue, i) => <p key={i} className="text-xs text-[hsl(var(--warning))]">⚠ {issue}</p>)}
                      </div>
                    )}

                    {device.latest_metric && (
                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                        <UsageTile icon={Cpu} label="CPU" value={device.latest_metric.cpu_usage_percent} />
                        <UsageTile icon={MemoryStick} label="Memory" value={device.latest_metric.ram_usage_percent} />
                        <UsageTile icon={HardDrive} label="Disk" value={device.latest_metric.disk_usage_percent} />
                      </div>
                    )}

                    <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                      <Section icon={Cpu} title="Hardware">
                        <Row label="OS" value={`${device.os_name ?? device.os_type} ${device.os_version ?? ""}`.trim()} />
                        <Row label="CPU" value={device.cpu_model ? `${device.cpu_model} (${device.cpu_cores ?? "?"} cores)` : null} />
                        <Row label="RAM" value={fmtGb(device.ram_total_gb)} />
                        <Row label="Disk" value={fmtGb(device.disk_total_gb)} />
                        <Row label="GPU" value={device.gpu_model} />
                      </Section>
                      <Section icon={Wifi} title="Network & identity">
                        <Row label="Local IP" value={device.local_ip} />
                        <Row label="Public IP" value={device.public_ip} />
                        <Row label="MAC" value={device.mac_address} />
                        <Row label="Serial number" value={device.serial_number} />
                        <Row label="Asset tag" value={device.asset_tag} />
                        <Row label="Agent version" value={device.agent_version} />
                      </Section>
                    </div>
                  </div>
                )}

                {tab === "metrics" && <MetricsTab metrics={metrics} />}
                {tab === "processes" && <ProcessesTab data={processData} />}
                {tab === "screen" && (
                  <ScreenTab deviceId={deviceId} screenshots={screenshots ?? []} selected={selectedShot} onSelect={setSelectedShot}
                    onRequest={() => void requestScreenshot()} isRequesting={screenshotMut.isPending} />
                )}
                {tab === "alerts" && <AlertsTab alerts={alerts} onAcknowledge={(id) => acknowledgeMut.mutate(id)} />}
                {tab === "allowed" && (
                  <AllowedAppsTab watchlist={watchlist ?? []} allowedApps={allowedApps ?? []}
                    onAllow={(domain) => addAllowedMut.mutate({ domain_or_app: domain })}
                    onRevoke={(id) => removeAllowedMut.mutate(id)}
                    isMutating={addAllowedMut.isPending || removeAllowedMut.isPending} />
                )}
              </>
            )}
          </section>

          {/* Right panel: summary + assignment */}
          <aside className="space-y-4 lg:sticky lg:top-4 lg:self-start" aria-label="Device summary">
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-4">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Monitor size={15} aria-hidden /> Summary</h3>
              {device ? (
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-[hsl(var(--foreground-muted))]">Status</span>
                    <Badge variant={statusVariant(device.status)}>{device.status}</Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[hsl(var(--foreground-muted))]">Health</span>
                    {device.health_score !== null && device.health_score < 70
                      ? <Badge variant="warning"><AlertTriangle size={10} aria-hidden className="mr-1" />{device.health_score}</Badge>
                      : <span className="font-semibold">{device.health_score ?? "—"}</span>}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[hsl(var(--foreground-muted))]">Last seen</span>
                    <span className="font-semibold">{fmtDate(device.last_seen_at)}</span>
                  </div>
                </div>
              ) : <Skeleton className="h-16 w-full" />}
            </div>

            <div className="rounded-xl border border-[hsl(var(--border))] p-4">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><User size={15} aria-hidden /> Assigned to</h3>
              {device?.assigned_employee ? (
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{device.assigned_employee.full_name}</p>
                    <p className="text-xs text-[hsl(var(--foreground-muted))]">{device.assigned_employee.employee_code}</p>
                  </div>
                  <button type="button" onClick={() => unassignMut.mutate()} disabled={unassignMut.isPending}
                    className="text-xs font-medium text-[hsl(var(--destructive))] hover:underline">Unassign</button>
                </div>
              ) : showAssign ? (
                <select aria-label="Select an employee" defaultValue=""
                  className="h-10 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm"
                  onChange={async (e) => {
                    if (!e.target.value) return;
                    try { await assignMut.mutateAsync(e.target.value); toast.success("Device assigned"); setShowAssign(false); }
                    catch { toast.error("Couldn't assign device"); }
                  }}>
                  <option value="" disabled>Select an employee…</option>
                  {employeesData?.items.map((emp) => <option key={emp.id} value={emp.id}>{emp.full_name} ({emp.employee_code})</option>)}
                </select>
              ) : (
                <button type="button" onClick={() => setShowAssign(true)}
                  className="w-full rounded-lg border border-dashed border-[hsl(var(--border-strong))] p-3 text-xs text-[hsl(var(--foreground-muted))] hover:border-[hsl(var(--brand-300))] hover:text-[hsl(var(--brand-700))]">
                  + Assign to an employee
                </button>
              )}
            </div>
          </aside>
        </div>

        {/* Action bar */}
        <div className="sticky bottom-0 z-10 space-y-3 border-t border-[hsl(var(--border))] bg-[hsl(var(--background))]/95 px-5 py-4 backdrop-blur sm:px-8">
          {showMessage && (
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void sendMessage(); }}>
              <input value={messageText} onChange={(e) => setMessageText(e.target.value)} placeholder="Message to show on screen…"
                aria-label="Message to show on the device"
                className="h-10 flex-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm outline-none focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]" />
              <Button type="submit" disabled={messageMut.isPending || !messageText.trim()}>
                {messageMut.isPending ? <Loader2 size={14} className="animate-spin" /> : "Send"}
              </Button>
            </form>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" onClick={() => void runAction("lock", "Lock")} disabled={!device} icon={<Lock size={14} className="mr-1.5" />}>Lock</Button>
            <Button variant="secondary" onClick={() => void runAction("restart", "Restart")} disabled={!device} icon={<RotateCcw size={14} className="mr-1.5" />}>Restart</Button>
            <Button variant="secondary" onClick={() => void runAction("shutdown", "Shut down")} disabled={!device} icon={<Power size={14} className="mr-1.5" />}>Shutdown</Button>
            <Button variant="secondary" onClick={() => setShowMessage((v) => !v)} disabled={!device} icon={<MessageSquare size={14} className="mr-1.5" />}>Message</Button>
            <button type="button" onClick={() => void decommission()} disabled={!device || decommissionMut.isPending}
              className="ml-auto inline-flex h-10 items-center gap-1.5 rounded-lg border border-[hsl(var(--destructive))]/30 px-4 text-sm font-semibold text-[hsl(var(--destructive))] hover:bg-[hsl(var(--status-error-bg))] disabled:opacity-50">
              <Trash2 size={14} aria-hidden /> Decommission
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

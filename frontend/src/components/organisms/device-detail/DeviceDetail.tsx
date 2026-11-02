"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  CalendarCheck, Camera, ArrowLeft, LayoutDashboard, Loader2, Lock, MessageSquare, Monitor, Power, RotateCcw,
  ShieldAlert, ShieldCheck, Trash2, User, Clock, LogIn, LogOut,
} from "lucide-react";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { cn } from "@/utils/cn";
import { Avatar, Badge, Button, EmptyState, PageHeader, Skeleton } from "@/components/atoms";
import { useEmployees } from "@/services/employee.service";
import {
  useAcknowledgeAlert, useActivityWatchlist, useAddAllowedApp, useAllowedApps, useAssignDevice, useDecommissionDevice,
  useDevice, useDeviceAction, useDeviceAlerts, useDeviceScreenshots,
  useMessageDevice, useRemoveAllowedApp, useRequestScreenshot, useUnassignDevice,
} from "@/services/devices.service";
import type { DeviceScreenshotItem } from "@/types";
import { fmtDate } from "./format";
import { AllowedAppsTab, AlertsTab, ScreenTab } from "./tabs";

// ── Attendance of whoever holds this computer ───────────────────────────────
interface DayRow {
  date: string; status: string; check_in: string | null; check_out: string | null;
  total_minutes: number | null; late_minutes: number | null; is_working: boolean;
}
interface HolderAttendance {
  assigned: boolean;
  today: DayRow | null;
  days: DayRow[];
  summary: { days: number; present: number; late: number; absent: number; on_leave: number; avg_minutes: number } | null;
}

function useHolderAttendance(deviceId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["device-attendance", deviceId],
    enabled,
    refetchInterval: 60_000,
    retry: false,
    queryFn: async () => (await apiClient.get<HolderAttendance>(`/devices/${deviceId}/attendance`, { params: { days: 14 } })).data,
  });
}

const fmtTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "—";
const fmtDay = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
const fmtHours = (m: number | null | undefined) =>
  m === null || m === undefined || m <= 0 ? "—" : `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
const statusLabel = (s: string) => s.replace(/_/g, " ");
const statusTone = (s: string) =>
  (s === "present" || s === "work_from_home" ? "success" : s === "absent" || s === "missed_punch" ? "error"
    : s === "late" || s === "half_day" ? "warning" : "outline") as "success" | "error" | "warning" | "outline";

// ── Local tab list (Metrics and Processes were device telemetry; Attendance replaces them) ──
type TabId = "overview" | "attendance" | "screen" | "alerts" | "allowed";
const TABS: { id: TabId; label: string; title: string; subtitle: string; icon: React.ElementType }[] = [
  { id: "overview", label: "Overview", title: "Employee overview", subtitle: "Who has this computer, and how their day is going.", icon: LayoutDashboard },
  { id: "attendance", label: "Attendance", title: "Attendance", subtitle: "Check-ins and hours for the last 14 days.", icon: CalendarCheck },
  { id: "screen", label: "Screen", title: "Screen", subtitle: "Capture the screen on demand.", icon: Camera },
  { id: "alerts", label: "Alerts", title: "Alerts", subtitle: "Flagged apps and sites on this computer.", icon: ShieldAlert },
  { id: "allowed", label: "Allowed apps", title: "Allowed apps", subtitle: "Stop alerts for apps this employee may use.", icon: ShieldCheck },
];

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

function Tile({ icon: Icon, label, value, hint }: { icon: React.ElementType; label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-[hsl(var(--border))] p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-[hsl(var(--foreground-muted))]">{label}</span>
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]">
          <Icon size={15} aria-hidden className="text-[hsl(var(--foreground-muted))]" />
        </span>
      </div>
      <p className="mt-2 font-heading text-2xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">{hint}</p>}
    </div>
  );
}

const statusVariant = (s: string) => (s === "online" ? "success" : s === "offline" ? "error" : "outline") as "success" | "error" | "outline";

function TodayTiles({ att }: { att: HolderAttendance | undefined }) {
  const t = att?.today;
  if (!att || !att.assigned) return null;
  if (!t) {
    return <p className="rounded-xl border border-dashed border-[hsl(var(--border))] p-4 text-sm text-[hsl(var(--foreground-muted))]">Not checked in today.</p>;
  }
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Tile icon={LogIn} label="Checked in" value={fmtTime(t.check_in)} hint={t.late_minutes ? `${t.late_minutes} min late` : statusLabel(t.status)} />
      <Tile icon={LogOut} label="Checked out" value={t.is_working ? "Working now" : fmtTime(t.check_out)} />
      <Tile icon={Clock} label="Worked today" value={fmtHours(t.total_minutes)} />
    </div>
  );
}

function AttendanceTab({ att, isLoading, isError, assigned }: { att: HolderAttendance | undefined; isLoading: boolean; isError: boolean; assigned: boolean }) {
  if (!assigned) {
    return <EmptyState icon={User} title="Not assigned to anyone" description="Assign this computer to an employee to see their attendance." />;
  }
  if (isLoading) return <div className="space-y-3"><Skeleton className="h-20 w-full" /><Skeleton className="h-40 w-full" /></div>;
  if (isError || !att) {
    return <p className="py-8 text-center text-sm text-[hsl(var(--foreground-muted))]">You don&apos;t have permission to view attendance.</p>;
  }
  const s = att.summary;
  return (
    <div className="space-y-5">
      {s && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Tile icon={CalendarCheck} label="Days present" value={String(s.present)} hint={`of the last ${s.days} days`} />
          <Tile icon={Clock} label="Late" value={String(s.late)} />
          <Tile icon={User} label="Absent" value={String(s.absent)} hint={s.on_leave ? `${s.on_leave} on leave` : undefined} />
          <Tile icon={Clock} label="Average day" value={fmtHours(s.avg_minutes)} />
        </div>
      )}
      {att.days.length === 0 ? (
        <p className="py-6 text-center text-sm text-[hsl(var(--foreground-muted))]">No attendance records in this period.</p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-[hsl(var(--border))]">
          <table className="w-full text-sm">
            <thead className="bg-[hsl(var(--background-subtle))] text-left text-xs text-[hsl(var(--foreground-muted))]">
              <tr><th className="px-4 py-2.5 font-medium">Date</th><th className="px-4 py-2.5 font-medium">Status</th><th className="px-4 py-2.5 font-medium">In</th><th className="px-4 py-2.5 font-medium">Out</th><th className="px-4 py-2.5 text-right font-medium">Worked</th></tr>
            </thead>
            <tbody className="divide-y divide-[hsl(var(--border))]">
              {att.days.map((d) => (
                <tr key={d.date}>
                  <td className="px-4 py-2.5 font-medium">{fmtDay(d.date)}</td>
                  <td className="px-4 py-2.5"><Badge variant={statusTone(d.status)}>{statusLabel(d.status)}</Badge></td>
                  <td className="px-4 py-2.5">{fmtTime(d.check_in)}</td>
                  <td className="px-4 py-2.5">{d.is_working ? "Working" : fmtTime(d.check_out)}</td>
                  <td className="px-4 py-2.5 text-right">{fmtHours(d.total_minutes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/**
 * Full-page device screen, employee-first: who has the computer, how their day is going,
 * and the actions that matter. CPU/memory/disk, hardware, network and process lists are
 * not shown -- they are IT-ops data, not something an HR admin works with.
 */
export function DeviceDetail({ deviceId }: { deviceId: string }) {
  const router = useRouter();
  const [tab, setTab] = useState<TabId>("overview");
  const [showAssign, setShowAssign] = useState(false);
  const [showMessage, setShowMessage] = useState(false);
  const [messageText, setMessageText] = useState("");
  const [selectedShot, setSelectedShot] = useState<DeviceScreenshotItem | null>(null);

  // /devices/<id>?tab=alerts  (links from the alerts page and the notification bell)
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    if (wanted && TABS.some((t) => t.id === wanted)) setTab(wanted as TabId);
  }, []);

  const { data: device, isLoading, isError } = useDevice(deviceId);
  const { data: screenshots } = useDeviceScreenshots(deviceId, tab === "screen");
  const { data: alerts } = useDeviceAlerts(deviceId, tab === "alerts");
  const { data: allowedApps } = useAllowedApps(deviceId, tab === "allowed");
  const { data: watchlist } = useActivityWatchlist();
  const { data: employeesData } = useEmployees({ page_size: 100 });
  const emp = device?.assigned_employee ?? null;
  const attendanceQ = useHolderAttendance(deviceId, !!emp && (tab === "overview" || tab === "attendance"));

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
    const who = emp?.full_name ? `${emp.full_name}'s computer` : "this computer";
    if (!window.confirm(`${label} ${who}? It will apply on the next check-in (within ~60s).`)) return;
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
    if (!window.confirm("Decommission this computer? This revokes its agent token and removes it from the active list. This can't be undone.")) return;
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
  const name = emp?.full_name ?? (device ? "Unassigned computer" : "Device");
  const subtitle = emp
    ? [emp.designation, emp.department].filter(Boolean).join(" · ") || emp.employee_code
    : device?.hostname ?? "Loading…";

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
        description={subtitle}
        action={<Button variant="secondary" onClick={() => router.push("/devices")} icon={<ArrowLeft size={15} className="mr-1.5" />}>Back</Button>}
      />

      <div className="mx-auto max-w-6xl overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]">
        {/* Section stepper */}
        <nav aria-label="Device sections" className="border-b border-[hsl(var(--border))] px-5 py-5 sm:px-8">
          <ol className="flex items-start overflow-x-auto">
            {TABS.map((t, i) => {
              const active = t.id === tab;
              const Icon = t.icon;
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
                    <Icon size={16} aria-hidden />
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
                    {emp ? (
                      <>
                        <TodayTiles att={attendanceQ.data} />
                        <Section icon={User} title="Employee">
                          <Row label="Name" value={emp.full_name} />
                          <Row label="Employee code" value={emp.employee_code} />
                          <Row label="Department" value={emp.department} />
                          <Row label="Designation" value={emp.designation} />
                          <Row label="Email" value={emp.email} />
                          <Row label="Phone" value={emp.phone} />
                        </Section>
                      </>
                    ) : (
                      <EmptyState icon={User} title="Not assigned to anyone"
                        description="Assign this computer to an employee to see their details and attendance here." />
                    )}
                  </div>
                )}

                {tab === "attendance" && (
                  <AttendanceTab att={attendanceQ.data} isLoading={attendanceQ.isLoading} isError={attendanceQ.isError} assigned={!!emp} />
                )}
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

          {/* Right panel: the employee + which computer */}
          <aside className="space-y-4 lg:sticky lg:top-4 lg:self-start" aria-label="Employee and computer">
            <div className="rounded-xl border border-[hsl(var(--border))] p-4">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><User size={15} aria-hidden /> Assigned to</h3>
              {emp ? (
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-3">
                    <Avatar name={emp.full_name ?? emp.employee_code} src={emp.avatar_url} size="md" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{emp.full_name}</p>
                      <p className="text-xs text-[hsl(var(--foreground-muted))]">{emp.employee_code}</p>
                      {emp.department && <p className="truncate text-xs text-[hsl(var(--foreground-muted))]">{emp.department}</p>}
                    </div>
                  </div>
                  <button type="button" onClick={() => unassignMut.mutate()} disabled={unassignMut.isPending}
                    className="shrink-0 text-xs font-medium text-[hsl(var(--destructive))] hover:underline">Unassign</button>
                </div>
              ) : showAssign ? (
                <select aria-label="Select an employee" defaultValue=""
                  className="h-10 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm"
                  onChange={async (e) => {
                    if (!e.target.value) return;
                    try { await assignMut.mutateAsync(e.target.value); toast.success("Computer assigned"); setShowAssign(false); }
                    catch { toast.error("Couldn't assign"); }
                  }}>
                  <option value="" disabled>Select an employee…</option>
                  {employeesData?.items.map((e2) => <option key={e2.id} value={e2.id}>{e2.full_name} ({e2.employee_code})</option>)}
                </select>
              ) : (
                <button type="button" onClick={() => setShowAssign(true)}
                  className="w-full rounded-lg border border-dashed border-[hsl(var(--border-strong))] p-3 text-xs text-[hsl(var(--foreground-muted))] hover:border-[hsl(var(--brand-300))] hover:text-[hsl(var(--brand-700))]">
                  + Assign to an employee
                </button>
              )}
            </div>

            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-4">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Monitor size={15} aria-hidden /> Computer</h3>
              {device ? (
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-[hsl(var(--foreground-muted))]">Name</span>
                    <span className="truncate font-medium">{device.device_name ?? device.hostname}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[hsl(var(--foreground-muted))]">Status</span>
                    <Badge variant={statusVariant(device.status)}>{device.status}</Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[hsl(var(--foreground-muted))]">Last seen</span>
                    <span className="font-semibold">{fmtDate(device.last_seen_at)}</span>
                  </div>
                </div>
              ) : <Skeleton className="h-16 w-full" />}
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

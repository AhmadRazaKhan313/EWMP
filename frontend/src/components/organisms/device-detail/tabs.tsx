"use client";

import { Activity, Camera, Check, Loader2, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/atoms";
import { useScreenshotImage } from "@/services/devices.service";
import type { AllowedAppItem, DeviceScreenshotItem } from "@/types";
import type { useDeviceAlerts, useDeviceMetrics, useDeviceProcesses } from "@/services/devices.service";
import { fmtDate } from "./format";

// ── Screen Tab ─────────────────────────────────────────────────────────────
export function ScreenTab({
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
        A screenshot is taken automatically about once a minute while the device is connected, and
        whenever you request one. Each capture is a still image — no recording. Old captures are
        deleted after a few days.
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
                    <span className="ml-1 opacity-70">{s.requested_by_id ? "· manual" : "· auto"}</span>
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
export function AllowedAppsTab({
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


type Metrics = NonNullable<ReturnType<typeof useDeviceMetrics>["data"]>;
type Processes = ReturnType<typeof useDeviceProcesses>["data"];
type Alerts = NonNullable<ReturnType<typeof useDeviceAlerts>["data"]>;

const empty = "rounded-xl border border-dashed border-[hsl(var(--border))] p-8 text-center text-sm text-[hsl(var(--foreground-muted))]";

// ── Metrics ────────────────────────────────────────────────────────────────
export function MetricsTab({ metrics }: { metrics: Metrics | undefined }) {
  if (!metrics || metrics.length === 0) {
    return <p className={empty}>No metrics yet — the agent reports every heartbeat interval.</p>;
  }
  return (
    <div className="space-y-1.5">
      <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-[hsl(var(--foreground-muted))]">
        <Activity size={12} aria-hidden /> LAST 24 HOURS ({metrics.length} points)
      </p>
      {metrics.slice(-20).reverse().map((m, i) => (
        <div key={i} className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] px-3 py-2 text-xs">
          <span className="text-[hsl(var(--foreground-muted))]">{new Date(m.recorded_at).toLocaleTimeString()}</span>
          <div className="flex gap-3 font-mono">
            <span>CPU {m.cpu_usage_percent?.toFixed(0) ?? "—"}%</span>
            <span>RAM {m.ram_usage_percent?.toFixed(0) ?? "—"}%</span>
            <span>Disk {m.disk_usage_percent?.toFixed(0) ?? "—"}%</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Processes ──────────────────────────────────────────────────────────────
export function ProcessesTab({ data }: { data: Processes }) {
  if (!data || data.processes.length === 0) return <p className={empty}>No process snapshot available yet.</p>;
  return (
    <div className="space-y-1.5">
      <p className="mb-2 text-xs text-[hsl(var(--foreground-muted))]">Captured {fmtDate(data.captured_at)} — top by memory usage</p>
      {data.processes.map((p) => (
        <div key={p.pid} className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] px-3 py-2 text-xs">
          <span className="truncate">{p.name} <span className="text-[hsl(var(--foreground-muted))]">#{p.pid}</span></span>
          <span className="font-mono">{p.memory_percent}% mem</span>
        </div>
      ))}
    </div>
  );
}

// ── Alerts ─────────────────────────────────────────────────────────────────
export function AlertsTab({ alerts, onAcknowledge }: { alerts: Alerts | undefined; onAcknowledge: (id: string) => void }) {
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-3 text-xs text-[hsl(var(--foreground-muted))]">
        <ShieldAlert size={13} aria-hidden className="mt-0.5 shrink-0" />
        Only flagged matches against the organization&apos;s watch-list are shown here — never a full browsing or activity history.
      </div>
      {!alerts || alerts.length === 0 ? (
        <p className={empty}>No flagged activity for this device.</p>
      ) : (
        alerts.map((a) => (
          <div key={a.id}
            className={`flex items-start justify-between gap-3 rounded-xl border p-3 ${
              a.is_acknowledged ? "border-[hsl(var(--border))] opacity-60" : "border-[hsl(var(--warning))]/40 bg-[hsl(var(--warning-subtle))]"
            }`}>
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
              <button type="button" onClick={() => onAcknowledge(a.id)} aria-label="Mark reviewed" title="Mark reviewed"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))]">
                <Check size={14} aria-hidden />
              </button>
            )}
          </div>
        ))
      )}
    </div>
  );
}

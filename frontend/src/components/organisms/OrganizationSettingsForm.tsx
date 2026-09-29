"use client";

/**
 * Settings → General. Replaces a mock (hardcoded "My Organization", a Save
 * button with no handler) — audit finding H-17. Reads and writes
 * GET/PATCH /organization; only fields that actually changed are sent.
 *
 * Read-only for users without `settings.manage` (the API enforces the same).
 */

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button, Card } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import {
  WORK_DAYS,
  useOrganizationSettings,
  useUpdateOrganizationSettings,
  type OrganizationSettings,
  type OrganizationSettingsUpdate,
  type WorkDay,
} from "@/services/organization.service";

const DAY_LABELS: Record<WorkDay, string> = {
  mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun",
};

const COMMON_CURRENCIES = ["PKR", "USD", "EUR", "GBP", "AED", "SAR", "INR", "BDT", "CAD", "AUD"];

const FALLBACK_TIMEZONES = [
  "UTC", "Asia/Karachi", "Asia/Dubai", "Asia/Riyadh", "Asia/Kolkata", "Asia/Dhaka",
  "Europe/London", "Europe/Berlin", "America/New_York", "America/Chicago",
  "America/Los_Angeles", "Australia/Sydney",
];

type Draft = Omit<OrganizationSettings, "id" | "slug">;

const EDITABLE: (keyof Draft)[] = [
  "name", "email", "phone", "website", "country", "timezone", "currency",
  "work_days", "standard_work_hours_per_day",
];

function toDraft(org: OrganizationSettings): Draft {
  return {
    name: org.name, email: org.email, phone: org.phone, website: org.website,
    country: org.country, timezone: org.timezone, currency: org.currency,
    work_days: org.work_days, standard_work_hours_per_day: org.standard_work_hours_per_day,
  };
}

function allTimezones(current: string | undefined): string[] {
  // Every IANA zone the browser knows; older browsers get a short list.
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  const zones = typeof intl.supportedValuesOf === "function"
    ? ["UTC", ...intl.supportedValuesOf("timeZone")]
    : FALLBACK_TIMEZONES;
  return current && !zones.includes(current) ? [current, ...zones] : zones;
}

function errorMessage(err: unknown): string {
  const data = (err as {
    response?: { data?: { message?: string; detail?: { message?: string }[] | unknown } };
  })?.response?.data;
  const first = Array.isArray(data?.detail) ? (data.detail[0] as { message?: string })?.message : undefined;
  if (first) return first.replace(/^Value error, /, "");
  return data?.message ?? "Couldn't save organization settings";
}

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

function Row({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[hsl(var(--border))] py-4 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        {description && <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">{description}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

const inputCls =
  "h-8 w-64 max-w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] disabled:opacity-60";

export function OrganizationSettingsForm(): JSX.Element {
  const { hasPermission } = useAuthStore();
  const canManage = hasPermission("settings.manage");

  const { data: org, isLoading, isError } = useOrganizationSettings();
  const update = useUpdateOrganizationSettings();
  const [draft, setDraft] = useState<Draft | null>(null);

  // Seed the draft from the server (again after each save).
  useEffect(() => {
    if (org) setDraft(toDraft(org));
  }, [org]);

  const changes = useMemo<OrganizationSettingsUpdate>(() => {
    if (!org || !draft) return {};
    const out: Record<string, unknown> = {};
    for (const key of EDITABLE) {
      if (!sameValue(draft[key], org[key])) out[key] = draft[key];
    }
    return out as OrganizationSettingsUpdate;
  }, [org, draft]);
  const isDirty = Object.keys(changes).length > 0;
  const timezones = useMemo(() => allTimezones(org?.timezone), [org?.timezone]);
  const currencies = useMemo(
    () => (org && !COMMON_CURRENCIES.includes(org.currency) ? [org.currency, ...COMMON_CURRENCIES] : COMMON_CURRENCIES),
    [org],
  );

  if (isLoading || (!draft && !isError)) {
    return (
      <Card>
        <div className="flex items-center gap-2 py-10 text-sm text-[hsl(var(--foreground-muted))]">
          <Loader2 size={16} className="animate-spin" /> Loading organization settings…
        </div>
      </Card>
    );
  }
  if (isError || !draft || !org) {
    return (
      <Card>
        <p className="py-10 text-center text-sm text-[hsl(var(--foreground-muted))]">
          Couldn&apos;t load organization settings. Please refresh the page.
        </p>
      </Card>
    );
  }

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => (d ? { ...d, [key]: value } : d));

  function toggleDay(day: WorkDay) {
    if (!draft) return;
    const has = draft.work_days.includes(day);
    if (has && draft.work_days.length === 1) {
      toast.error("At least one working day is required");
      return;
    }
    const next = has ? draft.work_days.filter((d) => d !== day) : [...draft.work_days, day];
    set("work_days", WORK_DAYS.filter((d) => next.includes(d)));
  }

  function save() {
    update.mutate(changes, {
      onSuccess: () => toast.success("Organization settings saved"),
      onError: (err) => toast.error(errorMessage(err)),
    });
  }

  const disabled = !canManage || update.isPending;
  const timezoneChanged = draft.timezone !== org.timezone;

  return (
    <Card padding={false}>
      <div className="border-b border-[hsl(var(--border))] px-5 py-4">
        <h3 className="font-heading text-sm font-semibold">Organization Settings</h3>
        {!canManage && (
          <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">
            View only — changing these needs the “Manage Organization Settings” permission.
          </p>
        )}
      </div>

      <div className="px-5">
        <Row label="Organization name">
          <input className={inputCls} value={draft.name} disabled={disabled}
                 onChange={(e) => set("name", e.target.value)} />
        </Row>
        <Row label="Contact email" description="Where EWMP sends organization-level notices">
          <input className={inputCls} type="email" value={draft.email} disabled={disabled}
                 onChange={(e) => set("email", e.target.value)} />
        </Row>
        <Row label="Phone">
          <input className={inputCls} value={draft.phone ?? ""} disabled={disabled}
                 onChange={(e) => set("phone", e.target.value || null)} />
        </Row>
        <Row label="Website">
          <input className={inputCls} placeholder="https://" value={draft.website ?? ""} disabled={disabled}
                 onChange={(e) => set("website", e.target.value || null)} />
        </Row>
        <Row label="Country">
          <input className={inputCls} value={draft.country ?? ""} disabled={disabled}
                 onChange={(e) => set("country", e.target.value || null)} />
        </Row>
        <Row label="Timezone" description="Decides which calendar day attendance belongs to and when overnight sessions close">
          <div className="flex flex-col items-end gap-1">
            <select className={inputCls} value={draft.timezone} disabled={disabled}
                    onChange={(e) => set("timezone", e.target.value)}>
              {timezones.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
            </select>
            {timezoneChanged && (
              <p className="flex max-w-64 items-start gap-1 text-xs text-[hsl(var(--warning))]">
                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                Applies from now on. Records already saved are not re-dated.
              </p>
            )}
          </div>
        </Row>
        <Row label="Currency" description="Default currency for the organization">
          <select className={inputCls} value={draft.currency} disabled={disabled}
                  onChange={(e) => set("currency", e.target.value)}>
            {currencies.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Row>
        <Row label="Work week" description="The organization's default working days">
          <div className="flex gap-1">
            {WORK_DAYS.map((day) => {
              const on = draft.work_days.includes(day);
              return (
                <button
                  key={day}
                  type="button"
                  disabled={disabled}
                  onClick={() => toggleDay(day)}
                  aria-pressed={on}
                  title={DAY_LABELS[day]}
                  className={`h-8 w-9 rounded-md text-xs font-medium transition-colors disabled:opacity-60 ${
                    on
                      ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                      : "bg-[hsl(var(--secondary))] text-[hsl(var(--foreground-muted))]"
                  }`}
                >
                  {DAY_LABELS[day]}
                </button>
              );
            })}
          </div>
        </Row>
        <Row label="Standard work hours per day" description="Used to convert hourly leave into days">
          <input className={`${inputCls} w-24`} type="number" min={0.5} max={24} step={0.5}
                 value={draft.standard_work_hours_per_day} disabled={disabled}
                 onChange={(e) => set("standard_work_hours_per_day", Number(e.target.value))} />
        </Row>
      </div>

      {canManage && (
        <div className="flex items-center gap-3 border-t border-[hsl(var(--border))] px-5 py-4">
          <Button size="sm" onClick={save} disabled={!isDirty || update.isPending}>
            {update.isPending ? "Saving…" : "Save changes"}
          </Button>
          {isDirty && !update.isPending && (
            <button
              type="button"
              className="text-xs text-[hsl(var(--foreground-muted))] hover:underline"
              onClick={() => setDraft(toDraft(org))}
            >
              Discard changes
            </button>
          )}
        </div>
      )}
    </Card>
  );
}

"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import apiClient from "@/services/api-client";

export interface WeekDay {
  date: string;
  weekday: string;
  hours: number;
  people: number;
  is_working_day: boolean;
  is_holiday: boolean;
  extra_day: boolean;
  is_today: boolean;
  is_future: boolean;
}
export interface WeeklyHours {
  week_start: string;
  week_end: string;
  scope: "employee" | "team";
  days: WeekDay[];
  total_hours: number;
  target_hours: number;
  working_days: number;
  hours_per_working_day: number;
  max_axis_hours: number;
}

const LABEL: Record<string, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function formatHours(h: number): string {
  const mins = Math.round(h * 60);
  const hh = Math.floor(mins / 60);
  const mm = mins % 60;
  return mm === 0 ? `${hh}h` : `${hh}h ${mm}m`;
}

export function useWeeklyHours(scope: "me" | "team", weekStart: string | null) {
  return useQuery({
    queryKey: ["dashboard-weekly-hours", scope, weekStart],
    queryFn: async () =>
      (await apiClient.get<WeeklyHours>("/dashboard/weekly-hours", {
        params: { scope, ...(weekStart ? { week_start: weekStart } : {}) },
      })).data,
    staleTime: 60_000,
  });
}

/** Pure view — Mon..Sun bars on a fixed 0-24h axis plus the weekly progress bar. */
export function WeeklyHoursView({ data }: { data: WeeklyHours }) {
  const axis = data.max_axis_hours || 24;
  const pct = data.target_hours > 0 ? Math.min(100, (data.total_hours / data.target_hours) * 100) : 0;
  const team = data.scope === "team";
  return (
    <div>
      <div className="flex h-44 items-end gap-2" role="img" aria-label="Hours worked per day">
        {data.days.map((d) => {
          const h = Math.min(axis, Math.max(0, d.hours));
          return (
            <div key={d.date} className="flex h-full flex-1 flex-col items-center justify-end gap-1"
              title={`${d.date}: ${formatHours(d.hours)}${team ? ` avg · ${d.people} people` : ""}`}>
              <span className="text-[11px] font-medium text-[hsl(var(--foreground-muted))]">{d.hours > 0 ? formatHours(d.hours) : ""}</span>
              <div className="flex w-full flex-1 items-end rounded-md bg-[hsl(var(--secondary))]">
                <div
                  data-testid={`bar-${d.weekday}`}
                  className={
                    "w-full rounded-md " +
                    (d.extra_day ? "bg-[hsl(var(--warning))]" : d.is_today ? "bg-[hsl(var(--brand-600))]" : "bg-[hsl(var(--brand-400))]")
                  }
                  style={{ height: `${(h / axis) * 100}%` }}
                />
              </div>
              <span className={"text-xs " + (d.is_today ? "font-semibold text-[hsl(var(--foreground))]" : "text-[hsl(var(--foreground-muted))]")}>
                {LABEL[d.weekday]}
              </span>
              <span className="h-3 text-[10px] text-[hsl(var(--foreground-muted))]">
                {d.extra_day ? "extra day" : d.is_holiday ? "holiday" : !d.is_working_day ? "off" : ""}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-4">
        <div className="flex items-center justify-between text-sm">
          <span className="text-[hsl(var(--foreground-muted))]">
            {team ? "Team average this week" : "Weekly progress"} · {data.working_days} working days
          </span>
          <span className="font-semibold">{formatHours(data.total_hours)} / {formatHours(data.target_hours)}</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-[hsl(var(--secondary))]">
          <div className="h-full rounded-full bg-[hsl(var(--brand-600))]" style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  );
}

export function WeeklyHoursChart({ canSeeTeam }: { canSeeTeam: boolean }) {
  const [scope, setScope] = useState<"me" | "team">("me");
  const [weekStart, setWeekStart] = useState<string | null>(null);
  const { data, isLoading } = useWeeklyHours(scope, weekStart);
  const current = data?.week_start ?? weekStart;

  const tab = (s: "me" | "team", label: string) => (
    <button type="button" onClick={() => setScope(s)} aria-pressed={scope === s}
      className={"rounded-md px-3 py-1 text-sm font-medium " + (scope === s
        ? "bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]"
        : "text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]")}>
      {label}
    </button>
  );

  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-[var(--shadow-xs)]">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-heading text-lg font-semibold leading-7">Hours this week</h3>
          {data && <p className="text-xs text-[hsl(var(--foreground-muted))]">{data.week_start} → {data.week_end}</p>}
        </div>
        <div className="flex items-center gap-2">
          {canSeeTeam && <div className="flex rounded-lg border border-[hsl(var(--border))] p-0.5">{tab("me", "Me")}{tab("team", "Team")}</div>}
          <div className="flex items-center">
            <button type="button" aria-label="Previous week" disabled={!current}
              onClick={() => current && setWeekStart(addDays(current, -7))}
              className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))]"><ChevronLeft size={16} /></button>
            <button type="button" aria-label="Next week" disabled={!current}
              onClick={() => current && setWeekStart(addDays(current, 7))}
              className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))]"><ChevronRight size={16} /></button>
          </div>
        </div>
      </div>
      {isLoading || !data
        ? <div className="h-52 animate-pulse rounded-lg bg-[hsl(var(--secondary))]" />
        : <WeeklyHoursView data={data} />}
    </div>
  );
}

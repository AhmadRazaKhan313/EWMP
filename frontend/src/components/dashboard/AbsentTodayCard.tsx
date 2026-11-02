"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { UserX, X } from "lucide-react";
import apiClient from "@/services/api-client";

export interface AbsentPerson {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  department_name: string | null;
  shift_name: string | null;
  status: "absent" | "not_checked_in";
}

export interface AbsentToday {
  date: string;
  absent: number;
  not_checked_in: number;
  total: number;
  employees: AbsentPerson[];
}

export function useAbsentToday(enabled: boolean) {
  return useQuery({
    queryKey: ["dashboard-absent"],
    queryFn: async () => (await apiClient.get<AbsentToday>("/dashboard/absent")).data,
    enabled,
    staleTime: 60_000,
  });
}

/** Red = confirmed absent (the shift is over); amber = working day, not in yet. */
export function AbsentBadge({ status }: { status: AbsentPerson["status"] }) {
  const absent = status === "absent";
  return (
    <span
      className={
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold " +
        (absent
          ? "bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))]"
          : "bg-[hsl(var(--warning-subtle))] text-[hsl(var(--warning))]")
      }
    >
      {absent ? "Absent" : "Not checked in"}
    </span>
  );
}

export function AbsentTodayCard() {
  const { data, isLoading, isError } = useAbsentToday(true);
  const [open, setOpen] = useState(false);
  const total = data?.total ?? 0;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Absent today — view list"
        className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 text-left shadow-[var(--shadow-xs)] transition-colors hover:border-[hsl(var(--error-600)/0.45)]"
      >
        <div className="flex items-start justify-between gap-3">
          <p className="text-sm font-medium text-[hsl(var(--foreground-muted))]">Absent Today</p>
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[hsl(var(--error-50))] text-[hsl(var(--error-600))]">
            <UserX size={20} aria-hidden />
          </span>
        </div>
        <div className="mt-1">
          {isLoading ? (
            <span className="inline-block h-8 w-16 animate-pulse rounded-md bg-[hsl(var(--secondary))]" />
          ) : (
            <p className="font-heading text-xl font-semibold text-[hsl(var(--foreground))]">{isError ? "—" : total}</p>
          )}
        </div>
        {isError && <p className="mt-2 text-xs text-[hsl(var(--destructive))]">Could not load — restart the backend</p>}
        {data && (
          <p className="mt-2 text-xs text-[hsl(var(--foreground-muted))]">
            {data.absent} absent · {data.not_checked_in} yet to check in
          </p>
        )}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-label="Absent today">
          <div className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} />
          <div className="relative flex max-h-[80vh] w-full max-w-lg flex-col rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-2xl">
            <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
              <div>
                <h3 className="font-heading text-base font-semibold">Absent today</h3>
                <p className="text-xs text-[hsl(var(--foreground-muted))]">
                  Working day only — holidays, leave and weekly-off are not counted.
                </p>
              </div>
              <button onClick={() => setOpen(false)} aria-label="Close"
                className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))]">
                <X size={16} />
              </button>
            </div>
            <div className="overflow-y-auto">
              {data && data.employees.length === 0 && (
                <p className="px-5 py-8 text-center text-sm text-[hsl(var(--foreground-muted))]">Everyone expected today is in.</p>
              )}
              <ul className="divide-y divide-[hsl(var(--border))]">
                {data?.employees.map((p) => (
                  <li key={p.employee_id} className="flex items-center justify-between gap-3 px-5 py-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{p.employee_name}</p>
                      <p className="truncate text-xs text-[hsl(var(--foreground-muted))]">
                        {[p.employee_code, p.department_name, p.shift_name].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                    <AbsentBadge status={p.status} />
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

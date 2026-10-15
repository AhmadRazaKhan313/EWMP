"use client";

import { Check, Clock, ListChecks, ShieldCheck } from "lucide-react";
import { cn } from "@/utils/cn";
import { STEPS } from "./wizard";

/**
 * Horizontal stepper. A step is clickable once it has been reached; later ones
 * stay disabled so required steps can't be skipped.
 */
export function Stepper({
  current, reached, onGo,
}: {
  current: number; reached: number; onGo: (index: number) => void;
}) {
  return (
    <nav aria-label="Employee onboarding steps">
      <ol className="flex items-start">
        {STEPS.map((s, i) => {
          const done = i < current;
          const active = i === current;
          const canGo = i <= reached && !active;
          return (
            <li key={s.id} className="relative flex flex-1 flex-col items-center">
              {i > 0 && (
                <span
                  aria-hidden
                  className={cn(
                    "absolute right-1/2 top-[18px] h-0.5 w-full -translate-y-1/2",
                    i <= current ? "bg-[hsl(var(--brand-600))]" : "bg-[hsl(var(--border))]",
                  )}
                />
              )}
              <button
                type="button"
                onClick={() => canGo && onGo(i)}
                disabled={!canGo && !active}
                aria-current={active ? "step" : undefined}
                aria-label={`Step ${i + 1}: ${s.label}${done ? " (completed)" : ""}`}
                className={cn(
                  "relative z-10 flex h-9 w-9 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors",
                  "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[hsl(var(--brand-100))]",
                  active && "border-[hsl(var(--brand-600))] bg-[hsl(var(--brand-600))] text-white shadow-[0_0_0_4px_hsl(var(--brand-100))]",
                  done && "border-[hsl(var(--brand-600))] bg-[hsl(var(--brand-600))] text-white",
                  !active && !done && (canGo
                    ? "border-[hsl(var(--brand-300))] bg-[hsl(var(--background))] text-[hsl(var(--brand-700))]"
                    : "border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--foreground-muted))]"),
                  canGo ? "cursor-pointer" : "cursor-default",
                )}
              >
                {done ? <Check size={16} aria-hidden /> : i + 1}
              </button>
              <span
                className={cn(
                  "mt-2 hidden text-xs font-medium sm:block",
                  active ? "text-[hsl(var(--brand-700))]" : "text-[hsl(var(--foreground-muted))]",
                )}
              >
                {s.label}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-center text-xs font-medium text-[hsl(var(--brand-700))] sm:hidden">
        Step {current + 1} of {STEPS.length} · {STEPS[current]?.label}
      </p>
    </nav>
  );
}

export function ProgressBar({ current }: { current: number }) {
  const pct = Math.round(((current + 1) / STEPS.length) * 100);
  return (
    <div className="flex items-center gap-4">
      <div
        role="progressbar" aria-valuemin={1} aria-valuemax={STEPS.length} aria-valuenow={current + 1}
        aria-label="Onboarding progress"
        className="h-1.5 flex-1 overflow-hidden rounded-full bg-[hsl(var(--secondary))]"
      >
        <div className="h-full rounded-full bg-[hsl(var(--brand-600))] transition-[width] duration-300" style={{ width: `${pct}%` }} />
      </div>
      <span className="shrink-0 text-xs text-[hsl(var(--foreground-muted))]">Step {current + 1} of {STEPS.length}</span>
    </div>
  );
}

/** Right-hand checklist + quick facts (stacks below the form on narrow screens). */
export function ChecklistPanel({
  current, reached, onGo,
}: {
  current: number; reached: number; onGo: (index: number) => void;
}) {
  return (
    <aside className="space-y-4 lg:sticky lg:top-4 lg:self-start" aria-label="Onboarding checklist">
      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[hsl(var(--foreground))]">
          <ListChecks size={15} aria-hidden /> Onboarding checklist
        </h3>
        <ol className="space-y-1">
          {STEPS.map((s, i) => {
            const done = i < current;
            const active = i === current;
            const canGo = i <= reached && !active;
            return (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => canGo && onGo(i)}
                  disabled={!canGo}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left text-sm transition-colors",
                    active ? "bg-[hsl(var(--brand-50))] font-semibold text-[hsl(var(--brand-700))]" : "text-[hsl(var(--foreground-subtle))]",
                    canGo && "hover:bg-[hsl(var(--accent))]",
                  )}
                >
                  <span
                    aria-hidden
                    className={cn(
                      "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                      done || active ? "bg-[hsl(var(--brand-600))] text-white" : "border border-[hsl(var(--border-strong))] text-[hsl(var(--foreground-muted))]",
                    )}
                  >
                    {done ? <Check size={11} /> : i + 1}
                  </span>
                  {s.check}
                </button>
              </li>
            );
          })}
        </ol>
      </div>

      <div className="rounded-xl border border-[hsl(var(--border))] p-4">
        <h3 className="mb-3 text-sm font-semibold text-[hsl(var(--foreground))]">Quick info</h3>
        <dl className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <dt className="flex items-center gap-2 text-[hsl(var(--foreground-muted))]"><ListChecks size={14} aria-hidden />Total steps</dt>
            <dd className="font-semibold">{STEPS.length}</dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="flex items-center gap-2 text-[hsl(var(--foreground-muted))]"><Clock size={14} aria-hidden />Required</dt>
            <dd className="font-semibold">Personal, Role</dd>
          </div>
        </dl>
      </div>

      <p className="flex items-start gap-2 px-1 text-xs text-[hsl(var(--foreground-muted))]">
        <ShieldCheck size={14} aria-hidden className="mt-0.5 shrink-0" />
        Employee details are only visible to people with the right permissions.
      </p>
    </aside>
  );
}

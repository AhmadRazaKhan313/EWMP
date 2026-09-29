"use client";

/**
 * Form and layout primitives shared by the payroll pages.
 *
 * `Input`, `Select` and `Label` were being redefined, character for
 * character, at the top of payroll/settings/page.tsx and
 * payroll/structures/SalaryStructureDrawer.tsx — and the two copies had
 * already drifted (different padding, one had a hover border, one
 * didn't). Adding six more pages would have made that seven copies. They
 * live here instead.
 *
 * Nothing in this file talks to the API except EmployeeSelect, which
 * needs the employee list to be a picker at all.
 */

import { useState } from "react";
import { X, Loader2, Search, AlertTriangle } from "lucide-react";
import { useEmployees } from "@/services/employee.service";
import { Button, Card, Skeleton } from "@/components/atoms";
import { cn } from "@/utils/cn";

// ── Form fields ───────────────────────────────────────────────────────────
export const fieldClass =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1.5 text-sm outline-none " +
  "transition-colors hover:border-[hsl(var(--border-strong))] focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1 " +
  "disabled:cursor-not-allowed disabled:opacity-60";

export function Label({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">
      {children}
      {required && <span className="ml-0.5 text-[hsl(var(--destructive))]">*</span>}
    </label>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(fieldClass, props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn(fieldClass, props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(fieldClass, "resize-none", props.className)} />;
}

export function Field({
  label, required, hint, children,
}: {
  label: string; required?: boolean; hint?: string; children: React.ReactNode;
}) {
  return (
    <div>
      <Label required={required}>{label}</Label>
      {children}
      {hint && <p className="mt-1 text-[11px] text-[hsl(var(--foreground-muted))]">{hint}</p>}
    </div>
  );
}

export function Checkbox({
  checked, onChange, label,
}: {
  checked: boolean; onChange: (v: boolean) => void; label: string;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

// ── Drawer ────────────────────────────────────────────────────────────────

/**
 * Right-hand drawer, matching PayslipDrawer / SalaryStructureDrawer's
 * existing chrome. The footer is a fixed row rather than part of the
 * scroll area, so the save button is reachable on a long form without
 * scrolling to the bottom of it.
 */
export function Drawer({
  title, description, onClose, children, footer, width = "max-w-xl",
}: {
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}) {
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className={cn("fixed right-0 top-0 z-50 flex h-full w-full flex-col bg-[hsl(var(--background))] shadow-2xl", width)}>
        <div className="flex items-start justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div>
            <h2 className="font-heading text-lg font-semibold">{title}</h2>
            {description && <p className="text-xs text-[hsl(var(--foreground-muted))]">{description}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">{children}</div>

        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-[hsl(var(--border))] px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </>
  );
}

export function SaveButton({
  onClick, disabled, pending, children = "Save",
}: {
  onClick: () => void; disabled?: boolean; pending?: boolean; children?: React.ReactNode;
}) {
  return (
    <Button onClick={onClick} disabled={disabled || pending} icon={pending ? <Loader2 size={14} className="animate-spin" /> : undefined}>
      {children}
    </Button>
  );
}

// ── Employee picker ───────────────────────────────────────────────────────

/**
 * Every compensation record hangs off an employee_id, and until now the
 * only way to supply one was to paste a UUID into Postman. This is a
 * searchable list rather than a <select> because an org with 400 staff
 * makes a native dropdown unusable, and because `/employees` already
 * accepts a `query` param — the filtering happens server-side.
 */
export function EmployeeSelect({
  value, onChange, disabled,
}: {
  value: string; onChange: (id: string, name: string) => void; disabled?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const { data, isPending } = useEmployees({ query: search || undefined, page_size: 20 });
  const employees = data?.items ?? [];
  const selected = employees.find((e) => e.id === value);

  return (
    <div className="relative">
      <div className="relative">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--foreground-muted))]" />
        <Input
          value={open ? search : (selected?.full_name ?? search)}
          disabled={disabled}
          placeholder="Search by name or code…"
          onFocus={() => setOpen(true)}
          onChange={(e) => { setSearch(e.target.value); setOpen(true); }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          className="pl-8"
        />
      </div>

      {open && (
        <div className="absolute z-10 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-lg">
          {isPending ? (
            <div className="space-y-1.5 p-2">
              <Skeleton className="h-8" />
              <Skeleton className="h-8" />
              <Skeleton className="h-8" />
            </div>
          ) : employees.length === 0 ? (
            <p className="px-3 py-3 text-sm text-[hsl(var(--foreground-muted))]">No employees match that search.</p>
          ) : (
            employees.map((e) => (
              <button
                key={e.id}
                type="button"
                onMouseDown={() => { onChange(e.id, e.full_name); setSearch(e.full_name); setOpen(false); }}
                className={cn(
                  "flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-[hsl(var(--accent))]",
                  e.id === value && "bg-[hsl(var(--accent))]",
                )}
              >
                <span>{e.full_name}</span>
                <span className="font-mono text-[11px] text-[hsl(var(--foreground-muted))]">{e.employee_code}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Resolves employee_id → name for list rows. The payroll serializers
 * return only the id, so without this every table would read
 * "a3f2c1e8-…" in its first column. One employee fetch is shared across
 * all six compensation tabs via TanStack's cache.
 */
export function useEmployeeNames() {
  const { data } = useEmployees({ page_size: 200 });
  const byId = new Map((data?.items ?? []).map((e) => [e.id, e]));
  return (id: string) => {
    const e = byId.get(id);
    return e ? { name: e.full_name, code: e.employee_code } : { name: "Unknown employee", code: id.slice(0, 8) };
  };
}

// ── Tabs ──────────────────────────────────────────────────────────────────
export function Tabs<T extends string>({
  tabs, active, onChange,
}: {
  tabs: { id: T; label: string; count?: number }[];
  active: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1 rounded-lg bg-[hsl(var(--secondary))] p-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors",
            active === t.id
              ? "bg-[hsl(var(--background))] text-[hsl(var(--foreground))] shadow-sm"
              : "text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]",
          )}
        >
          {t.label}
          {t.count !== undefined && t.count > 0 && (
            <span className="rounded-full bg-[hsl(var(--info-subtle))] px-1.5 text-[10px] text-[hsl(var(--info))]">
              {t.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

// ── Load / error states ───────────────────────────────────────────────────

/**
 * A failed request is not an empty list. Pages that only checked
 * `items.length === 0` told people "nothing here yet" when the real
 * answer was a 403 or an unreachable server.
 */
export function QueryError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const status = (error as { response?: { status?: number } })?.response?.status;
  const message =
    !((error as { response?: unknown })?.response)
      ? "Can't reach the server. Check your connection, then try again."
      : status === 403
        ? "You don't have permission to view this."
        : (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Something went wrong loading this.";

  return (
    <Card>
      <div className="flex items-start gap-3 py-2">
        <AlertTriangle size={18} className="mt-0.5 shrink-0 text-[hsl(var(--destructive))]" />
        <div>
          <p className="text-sm font-medium">{message}</p>
          {onRetry && (
            <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
              Try again
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <Card padding={false}>
      <div className="divide-y divide-[hsl(var(--border))]">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-5 py-4">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-24" />
            <Skeleton className="ml-auto h-4 w-20" />
          </div>
        ))}
      </div>
    </Card>
  );
}

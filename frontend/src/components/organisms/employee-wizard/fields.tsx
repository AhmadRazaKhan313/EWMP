"use client";

import { useFormContext } from "react-hook-form";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { cn } from "@/utils/cn";
import type { EmployeeWizardValues } from "./wizard";

type Name = keyof EmployeeWizardValues;

const control =
  "w-full rounded-lg border bg-[hsl(var(--background))] px-3 text-sm text-[hsl(var(--foreground))] outline-none transition-colors " +
  "placeholder:text-[hsl(var(--foreground-muted))] focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))] " +
  "disabled:cursor-not-allowed disabled:opacity-60";

function borderFor(invalid: boolean) {
  return invalid
    ? "border-[hsl(var(--destructive))]"
    : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]";
}

/** Label + control slot + hint/error, wired for screen readers. */
export function Field({
  name, label, required, hint, error, children, className,
}: {
  name: string;
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label htmlFor={`f-${name}`} className="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">
        {label}
        {required && (
          <>
            <span aria-hidden className="ml-0.5 text-[hsl(var(--destructive))]">*</span>
            <span className="sr-only"> (required)</span>
          </>
        )}
      </label>
      {children}
      {error ? (
        <p id={`e-${name}`} role="alert" className="mt-1.5 text-xs text-[hsl(var(--destructive))]">{error}</p>
      ) : hint ? (
        <p id={`h-${name}`} className="mt-1.5 text-xs text-[hsl(var(--foreground-muted))]">{hint}</p>
      ) : null}
    </div>
  );
}

function describedBy(name: string, error?: string, hint?: string) {
  return error ? `e-${name}` : hint ? `h-${name}` : undefined;
}

export function TextField({
  name, label, required, hint, icon: Icon, className, ...input
}: {
  name: Name;
  label: string;
  required?: boolean;
  hint?: string;
  icon?: React.ElementType;
  className?: string;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "name" | "className">) {
  const { register, formState: { errors } } = useFormContext<EmployeeWizardValues>();
  const error = errors[name]?.message as string | undefined;
  return (
    <Field name={name} label={label} required={required} hint={hint} error={error} className={className}>
      <div className="relative">
        {Icon && <Icon size={15} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[hsl(var(--foreground-muted))]" />}
        <input
          id={`f-${name}`}
          aria-invalid={!!error}
          aria-describedby={describedBy(name, error, hint)}
          aria-required={required}
          {...input}
          {...register(name)}
          className={cn(control, "h-11", Icon && "pl-9", borderFor(!!error))}
        />
      </div>
    </Field>
  );
}

export function SelectField({
  name, label, required, hint, icon: Icon, className, children, disabled,
}: {
  name: Name;
  label: string;
  required?: boolean;
  hint?: string;
  icon?: React.ElementType;
  className?: string;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  const { register, formState: { errors } } = useFormContext<EmployeeWizardValues>();
  const error = errors[name]?.message as string | undefined;
  return (
    <Field name={name} label={label} required={required} hint={hint} error={error} className={className}>
      <div className="relative">
        {Icon && <Icon size={15} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[hsl(var(--foreground-muted))]" />}
        <select
          id={`f-${name}`}
          disabled={disabled}
          aria-invalid={!!error}
          aria-describedby={describedBy(name, error, hint)}
          aria-required={required}
          {...register(name)}
          className={cn(control, "h-11", Icon && "pl-9", borderFor(!!error))}
        >
          {children}
        </select>
      </div>
    </Field>
  );
}

/** Honest state for a dropdown fed by the API: loading, failed, or empty. */
export function OptionsNotice({
  isLoading, isError, isEmpty, what, onRetry,
}: {
  isLoading: boolean; isError: boolean; isEmpty: boolean; what: string; onRetry: () => void;
}) {
  if (isLoading) return <p className="mt-1.5 text-xs text-[hsl(var(--foreground-muted))]">Loading {what}…</p>;
  if (isError) {
    return (
      <p className="mt-1.5 flex items-center gap-1.5 text-xs text-[hsl(var(--destructive))]">
        <AlertTriangle size={12} aria-hidden /> Couldn&apos;t load {what}.
        <button type="button" onClick={onRetry} className="inline-flex items-center gap-1 font-medium underline">
          <RefreshCw size={11} aria-hidden /> Retry
        </button>
      </p>
    );
  }
  if (isEmpty) return <p className="mt-1.5 text-xs text-[hsl(var(--foreground-muted))]">No {what} set up yet.</p>;
  return null;
}

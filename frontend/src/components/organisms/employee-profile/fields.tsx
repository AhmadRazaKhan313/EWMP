"use client";

import { forwardRef } from "react";
import { cn } from "@/utils/cn";

// Small form building blocks shared by the Employee drawer and its profile
// sections. They were private to EmployeeDrawer.tsx; pulled out so the new
// sections (family, addresses, pay items, emergency contacts…) use the exact
// same look.

export function Label({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="block text-xs font-medium text-[hsl(var(--foreground-subtle))] mb-1">
      {children} {required && <span className="text-[hsl(var(--destructive))]">*</span>}
    </label>
  );
}

// forwardRef matters: react-hook-form's register() hands back a `ref`. React 18
// does not pass `ref` to a plain function component, so without this the form
// could not show default values (Edit mode, list rows) or read the field.
export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement> & { error?: boolean }>(
  function Input({ error, className, ...props }, ref) {
  return (
    <input
      {...props}
      ref={ref}
      className={cn(
        "w-full rounded-md border px-3 py-2 text-sm outline-none transition-colors",
        "bg-[hsl(var(--background))] placeholder:text-[hsl(var(--foreground-muted))]",
        "focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]",
        "disabled:opacity-60",
        error
          ? "border-[hsl(var(--destructive))]"
          : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
        className,
      )}
    />
  );
});

export const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement> & { error?: boolean }>(
  function Select({ error, children, className, ...props }, ref) {
  return (
    <select
      {...props}
      ref={ref}
      className={cn(
        "w-full rounded-md border px-3 py-2 text-sm outline-none transition-colors",
        "bg-[hsl(var(--background))]",
        "focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]",
        error
          ? "border-[hsl(var(--destructive))]"
          : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
        className,
      )}
    >
      {children}
    </select>
  );
});

export function SectionHeader({ icon: Icon, title }: { icon: React.ElementType; title: string }) {
  return (
    <div className="flex items-center gap-2 border-b border-[hsl(var(--border))] pb-2 mb-4">
      <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[hsl(var(--secondary))]">
        <Icon size={13} className="text-[hsl(var(--foreground-subtle))]" />
      </div>
      <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">{title}</h3>
    </div>
  );
}

/**
 * Atom components — smallest reusable UI units.
 * No business logic. No API calls. Pure presentation.
 */

import { cn } from "@/utils/cn";

// ── Badge ─────────────────────────────────────────────────────────────────────
type BadgeVariant = "default" | "success" | "warning" | "error" | "info" | "outline";

const badgeVariants: Record<BadgeVariant, string> = {
  default: "bg-[hsl(var(--secondary))] text-[hsl(var(--foreground-subtle))]",
  success: "bg-[hsl(var(--status-active-bg))] text-[hsl(var(--status-active-fg))]",
  warning: "bg-[hsl(var(--status-warning-bg))] text-[hsl(var(--status-warning-fg))]",
  error:   "bg-[hsl(var(--status-error-bg))] text-[hsl(var(--status-error-fg))]",
  info:    "bg-[hsl(var(--info-subtle))] text-[hsl(var(--info))]",
  outline: "border border-[hsl(var(--border))] text-[hsl(var(--foreground-subtle))]",
};

export function Badge({
  children,
  variant = "default",
  className,
}: {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
        badgeVariants[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-md", className)} />;
}

export function SkeletonTable({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="grid gap-4" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
          {Array.from({ length: cols }).map((_, j) => (
            <Skeleton key={j} className="h-9" />
          ))}
        </div>
      ))}
    </div>
  );
}

// ── StatusDot ─────────────────────────────────────────────────────────────────
type StatusColor = "green" | "yellow" | "red" | "gray" | "blue";

const dotColors: Record<StatusColor, string> = {
  green:  "bg-[hsl(var(--success))]",
  yellow: "bg-[hsl(var(--warning))]",
  red:    "bg-[hsl(var(--destructive))]",
  gray:   "bg-[hsl(var(--foreground-muted))]",
  blue:   "bg-[hsl(var(--info))]",
};

export function StatusDot({
  color = "gray",
  pulse = false,
  label,
}: {
  color?: StatusColor;
  pulse?: boolean;
  label?: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          dotColors[color],
          pulse && "status-dot-pulse",
        )}
      />
      {label && <span className="text-sm">{label}</span>}
    </span>
  );
}

// ── PageHeader ────────────────────────────────────────────────────────────────
export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between">
      <div>
        <h1 className="font-heading text-xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="mt-0.5 text-sm text-[hsl(var(--foreground-muted))]">{description}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

// ── Card ──────────────────────────────────────────────────────────────────────
export function Card({
  children,
  className,
  padding = true,
}: {
  children: React.ReactNode;
  className?: string;
  padding?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]",
        padding && "p-5",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
      <div>
        <h3 className="font-heading text-sm font-semibold">{title}</h3>
        {description && (
          <p className="text-xs text-[hsl(var(--foreground-muted))]">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}

// ── Button ────────────────────────────────────────────────────────────────────
type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "destructive";
type ButtonSize = "sm" | "md" | "lg";

const buttonVariants: Record<ButtonVariant, string> = {
  primary:     "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))]",
  secondary:   "bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] hover:bg-[hsl(var(--secondary-hover))]",
  outline:     "border border-[hsl(var(--border))] bg-transparent hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground))]",
  ghost:       "bg-transparent hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground))]",
  destructive: "bg-[hsl(var(--destructive))] text-white hover:opacity-90",
};

const buttonSizes: Record<ButtonSize, string> = {
  sm: "h-7 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  lg: "h-10 px-5 text-sm gap-2",
};

export function Button({
  children,
  variant = "primary",
  size = "md",
  className,
  disabled,
  onClick,
  type = "button",
  icon,
}: {
  children: React.ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit" | "reset";
  icon?: React.ReactNode;
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex items-center justify-center rounded-md font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        buttonVariants[variant],
        buttonSizes[size],
        className,
      )}
    >
      {icon}
      {children}
    </button>
  );
}

// ── Empty State ───────────────────────────────────────────────────────────────
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: React.ElementType;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-[hsl(var(--secondary))]">
        <Icon size={24} className="text-[hsl(var(--foreground-muted))]" />
      </div>
      <h3 className="font-heading text-base font-semibold">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm text-[hsl(var(--foreground-muted))]">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

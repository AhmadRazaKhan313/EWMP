/**
 * Atom components — smallest reusable UI units.
 * No business logic. No API calls. Pure presentation.
 */

import { cn } from "@/utils/cn";

// ── Badge ─────────────────────────────────────────────────────────────────────
// Untitled UI "Badge, modern": white pill-square (6px radius) with a hairline
// border, a coloured dot and 12px medium gray-700 text (Figma: Customers table).
type BadgeVariant = "default" | "brand" | "success" | "warning" | "error" | "info" | "outline";

const badgeDots: Record<BadgeVariant, string> = {
  default: "bg-[hsl(var(--gray-400))]",
  brand:   "bg-[hsl(var(--brand-500))]",
  success: "bg-[hsl(var(--success))]",
  warning: "bg-[hsl(var(--warning))]",
  error:   "bg-[hsl(var(--destructive))]",
  info:    "bg-[hsl(var(--info))]",
  outline: "bg-[hsl(var(--gray-400))]",
};

export function Badge({
  children,
  variant = "default",
  className,
  dot = true,
}: {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
  /** Show the coloured status dot (default). */
  dot?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-[hsl(var(--border-strong))]",
        "bg-[hsl(var(--card))] px-1.5 py-0.5 text-xs font-medium text-[hsl(var(--foreground-subtle))]",
        "shadow-[var(--shadow-xs)]",
        className,
      )}
    >
      {dot && <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", badgeDots[variant])} />}
      {children}
    </span>
  );
}

// ── Avatar + AvatarLabelGroup ─────────────────────────────────────────────────
// Untitled UI "Avatar label group": round avatar (photo or initials) with a name
// and optional supporting text beside it.
type AvatarSize = "xs" | "sm" | "md" | "lg" | "xl";

const avatarSizes: Record<AvatarSize, { box: string; text: string; name: string; sub: string }> = {
  xs: { box: "h-6 w-6",   text: "text-[10px]", name: "text-sm",  sub: "text-xs" },
  sm: { box: "h-8 w-8",   text: "text-xs",     name: "text-sm",  sub: "text-xs" },
  md: { box: "h-10 w-10", text: "text-sm",     name: "text-sm",  sub: "text-sm" },
  lg: { box: "h-12 w-12", text: "text-base",   name: "text-base", sub: "text-sm" },
  xl: { box: "h-16 w-16", text: "text-xl",     name: "text-lg",  sub: "text-sm" },
};

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0]![0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]![0] ?? "") : "";
  return (first + last).toUpperCase();
}

export function Avatar({
  name,
  src,
  size = "md",
  className,
}: {
  name: string;
  src?: string | null;
  size?: AvatarSize;
  className?: string;
}) {
  const sz = avatarSizes[size] ?? avatarSizes.md;
  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full",
        "bg-[hsl(var(--accent))] font-semibold text-[hsl(var(--accent-foreground))]",
        sz.box,
        sz.text,
        className,
      )}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={name} className="h-full w-full object-cover" />
      ) : (
        initialsOf(name)
      )}
      <span aria-hidden className="pointer-events-none absolute inset-0 rounded-full border-[0.75px] border-black/10" />
    </span>
  );
}

export function AvatarLabelGroup({
  name,
  subtext,
  src,
  size = "md",
  className,
}: {
  name: string;
  subtext?: string | null;
  src?: string | null;
  size?: AvatarSize;
  className?: string;
}) {
  const sz = avatarSizes[size] ?? avatarSizes.md;
  return (
    <div className={cn("flex min-w-0 items-center gap-3", className)}>
      <Avatar name={name} src={src} size={size} />
      <div className="min-w-0">
        <p className={cn("truncate font-medium text-[hsl(var(--foreground))]", sz.name)}>{name}</p>
        {subtext && (
          <p className={cn("truncate text-[hsl(var(--foreground-muted))]", sz.sub)}>{subtext}</p>
        )}
      </div>
    </div>
  );
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
// Untitled UI "Horizontal tabs, underline": 14px semibold, brand underline on the
// active tab, optional count pill. Accepts `{ value }` or `{ id }` per tab and
// `active` or `value` for the selected one, so existing call sites keep working.
export interface TabItem<T extends string = string> {
  value?: T;
  id?: T;
  label: string;
  count?: number;
}

export function Tabs<T extends string = string>({
  tabs,
  active,
  value,
  onChange,
  className,
}: {
  tabs: TabItem<T>[];
  active?: T;
  value?: T;
  onChange?: (next: T) => void;
  className?: string;
}) {
  const selected = active ?? value;
  return (
    <div role="tablist" className={cn("flex flex-wrap gap-3 border-b border-[hsl(var(--border))]", className)}>
      {tabs.map((t) => {
        const key = (t.id ?? t.value ?? t.label) as T;
        const isActive = key === selected;
        return (
          <button
            key={String(key)}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange?.(key)}
            className={cn(
              "-mb-px flex items-center gap-2 border-b-2 px-1 pb-3 text-sm font-semibold transition-colors",
              isActive
                ? "border-[hsl(var(--brand-600))] text-[hsl(var(--accent-foreground))]"
                : "border-transparent text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground-subtle))]",
            )}
          >
            {t.label}
            {t.count !== undefined && (
              <span className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] px-2 py-0.5 text-xs font-medium text-[hsl(var(--foreground-subtle))]">
                {t.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
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
  breadcrumb,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  breadcrumb?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        {breadcrumb && <div className="mb-2">{breadcrumb}</div>}
        <h1 className="font-heading text-2xl font-semibold leading-8 text-[hsl(var(--foreground))]">{title}</h1>
        {description && (
          <p className="mt-1 text-base text-[hsl(var(--foreground-muted))]">{description}</p>
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
        "rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-[var(--shadow-xs)]",
        padding && "p-6",
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
    <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-5">
      <div>
        <h3 className="font-heading text-lg font-semibold leading-7">{title}</h3>
        {description && (
          <p className="text-sm text-[hsl(var(--foreground-muted))]">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}

// ── Button ────────────────────────────────────────────────────────────────────
type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "destructive";
type ButtonSize = "sm" | "md" | "lg";

// Untitled UI buttons: 8px radius, 14px semibold. Primary and secondary carry the
// "skeuomorphic" shadow (drop shadow + 1px edge + soft inner bottom) from the Figma.
const SECONDARY =
  "border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] text-[hsl(var(--foreground-subtle))] " +
  "shadow-[var(--shadow-xs)] hover:bg-[hsl(var(--background-subtle))] hover:text-[hsl(var(--foreground))]";

const buttonVariants: Record<ButtonVariant, string> = {
  primary:
    "border border-[hsl(var(--brand-600))] bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] " +
    "shadow-[var(--shadow-skeuo)] hover:bg-[hsl(var(--primary-hover))]",
  secondary:   SECONDARY,
  outline:     SECONDARY,
  ghost:       "bg-transparent text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--background-subtle))] hover:text-[hsl(var(--foreground-subtle))]",
  destructive:
    "border border-[hsl(var(--destructive))] bg-[hsl(var(--destructive))] text-white " +
    "shadow-[var(--shadow-skeuo)] hover:opacity-90",
};

const buttonSizes: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-sm gap-1",
  md: "h-10 px-4 text-sm gap-1",
  lg: "h-11 px-[18px] text-base gap-1.5",
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
        "inline-flex items-center justify-center rounded-md font-semibold transition-colors",
        "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[hsl(var(--brand-100))]",
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

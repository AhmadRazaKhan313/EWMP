import type { ReactNode } from "react";

/**
 * Shared presentational primitives for the desktop app.
 *
 * Mirrors the atoms/ layer described in skills/design-system/SKILL.md,
 * collapsed into one file because the desktop app has a fraction of the
 * web app's component surface — splitting six small components across six
 * directories would be ceremony, not structure.
 *
 * Rule for everything here: no business logic, no API calls, no token
 * hardcoding. Colours come from hsl(var(--token)) only.
 */

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// ── Card ──────────────────────────────────────────────────────────────────
// Same surface as the web dashboard's cards: white, 16px radius, hairline
// border and the xs shadow. Floating surfaces (widget, dropdowns) use
// --shadow-sm directly instead of this component.

export function Card({
  children,
  className,
  padded = true,
  testId,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
  testId?: string;
}): JSX.Element {
  return (
    <section
      data-testid={testId}
      className={cn(
        "rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-[var(--shadow-xs)]",
        padded && "p-5",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  title,
  action,
  icon,
}: {
  title: string;
  action?: ReactNode;
  icon?: ReactNode;
}): JSX.Element {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h3 className="flex items-center gap-2 font-heading text-base font-semibold text-[hsl(var(--foreground))]">
        {icon}
        {title}
      </h3>
      {action}
    </div>
  );
}

// ── Badge ─────────────────────────────────────────────────────────────────
// Maps to the --status-* tokens. `warning` is the one to reach for on
// anything PENDING or OVERTIME — see the house rule in globals.css: orange
// means waiting, red means wrong.

type BadgeVariant = "default" | "success" | "warning" | "error" | "info" | "outline";

const BADGE_STYLES: Record<BadgeVariant, string> = {
  default: "bg-[hsl(var(--muted))] text-[hsl(var(--foreground-muted))]",
  success: "bg-[hsl(var(--status-active-bg))] text-[hsl(var(--status-active-fg))]",
  warning: "bg-[hsl(var(--status-warning-bg))] text-[hsl(var(--status-warning-fg))]",
  error: "bg-[hsl(var(--status-error-bg))] text-[hsl(var(--status-error-fg))]",
  info: "bg-[hsl(var(--info-subtle))] text-[hsl(var(--info))]",
  outline: "border border-[hsl(var(--border-strong))] text-[hsl(var(--foreground-muted))]",
};

export function Badge({
  children,
  variant = "default",
  dot = false,
  className,
}: {
  children: ReactNode;
  variant?: BadgeVariant;
  /** A small coloured dot before the label — matches the web app's Badge. */
  dot?: boolean;
  className?: string;
}): JSX.Element {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-[var(--radius-chip)] px-2 py-0.5 text-xs font-medium",
        dot && "pl-1.5",
        BADGE_STYLES[variant],
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function StatusDot({
  color = "gray",
  pulse = false,
}: {
  color?: "green" | "orange" | "red" | "indigo" | "gray";
  pulse?: boolean;
}): JSX.Element {
  const map: Record<string, string> = {
    green: "bg-[hsl(var(--success))]",
    orange: "bg-[hsl(var(--warning))]",
    red: "bg-[hsl(var(--destructive))]",
    indigo: "bg-[hsl(var(--primary))]",
    gray: "bg-[hsl(var(--foreground-muted))]",
  };
  return <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", map[color], pulse && "status-dot-pulse")} />;
}

// ── Button ────────────────────────────────────────────────────────────────

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "warning";

const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary:
    "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] shadow-skeuo hover:bg-[hsl(var(--primary-hover))]",
  secondary:
    "border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] text-[hsl(var(--secondary-foreground))] shadow-skeuo hover:bg-[hsl(var(--background-subtle))]",
  ghost:
    "text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]",
  danger:
    "bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] shadow-skeuo hover:opacity-90",
  warning:
    "bg-[hsl(var(--warning))] text-white shadow-skeuo hover:opacity-90",
};

export function Button({
  children,
  variant = "primary",
  size = "md",
  className,
  ...rest
}: {
  children: ReactNode;
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
} & React.ButtonHTMLAttributes<HTMLButtonElement>): JSX.Element {
  const sizes = {
    sm: "px-2.5 py-1.5 text-xs",
    md: "px-3.5 py-2.5 text-sm",
    lg: "px-5 py-3 text-sm",
  };
  return (
    <button
      {...rest}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-[var(--radius-control)] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55",
        BUTTON_STYLES[variant],
        sizes[size],
        className,
      )}
    >
      {children}
    </button>
  );
}

// ── StatBand ──────────────────────────────────────────────────────────────
// A row of stat cards, styled exactly like the web dashboard's: white card,
// label + tinted icon tile on top, the figure under it, small hint lines at
// the bottom. (It used to be one solid indigo strip.)

export interface StatBandItem {
  icon?: ReactNode;
  label: string;
  value: string;
  /** Up to two small split-lines under the value. */
  breakdown?: string[];
  testId?: string;
}

export function StatBand({ items }: { items: StatBandItem[] }): JSX.Element {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {items.map((item) => (
        <div
          key={item.label}
          data-testid={item.testId}
          className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 shadow-[var(--shadow-xs)]"
        >
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-medium text-[hsl(var(--foreground-muted))]">{item.label}</p>
            {item.icon && (
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]">
                {item.icon}
              </span>
            )}
          </div>
          <p className="num mt-1 font-heading text-xl font-semibold text-[hsl(var(--foreground))]">{item.value}</p>
          {item.breakdown && item.breakdown.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-x-3 text-xs text-[hsl(var(--foreground-muted))]">
              {item.breakdown.map((b) => (
                <span key={b}>{b}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── ProgressBar ───────────────────────────────────────────────────────────
// Used on attendance rows and leave balances. `segments` rather than a
// single value so a day can show worked + overtime in one bar.

export function ProgressBar({
  segments,
  className,
}: {
  segments: Array<{ percent: number; token: string; key: string }>;
  className?: string;
}): JSX.Element {
  return (
    <div
      className={cn(
        "flex h-2 min-w-[100px] overflow-hidden rounded-full bg-[hsl(var(--border))]",
        className,
      )}
    >
      {segments.map((s) => (
        <span
          key={s.key}
          className="h-full"
          style={{ width: `${Math.min(100, Math.max(0, s.percent))}%`, backgroundColor: `hsl(var(${s.token}))` }}
        />
      ))}
    </div>
  );
}

// ── States ────────────────────────────────────────────────────────────────
// An empty screen is an invitation to act, not a dead end — every
// EmptyState takes an optional action for that reason.

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}): JSX.Element {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
      <span className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))]">
        {icon}
      </span>
      <p className="font-heading text-sm font-semibold text-[hsl(var(--foreground))]">{title}</p>
      <p className="max-w-[38ch] text-xs leading-relaxed text-[hsl(var(--foreground-muted))]">{body}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

const AVATAR_SIZES: Record<"sm" | "md" | "lg", string> = {
  sm: "h-8 w-8 text-xs",
  md: "h-10 w-10 text-sm",
  lg: "h-12 w-12 text-base",
};

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function Avatar({
  src,
  name,
  size = "md",
  className,
}: {
  src?: string | null;
  name: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}): JSX.Element {
  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-[hsl(var(--brand-100))] font-medium text-[hsl(var(--brand-700))]",
        AVATAR_SIZES[size],
        className,
      )}
    >
      {src ? (
        <img src={src} alt="" className="h-full w-full object-cover" />
      ) : (
        initialsOf(name)
      )}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }): JSX.Element {
  return <div aria-hidden className={cn("skeleton", className)} />;
}

/** Rows of shimmer sized like the list they stand in for, so the layout
 * does not jump when real data lands. */
export function SkeletonList({ rows = 3, height = "h-14" }: { rows?: number; height?: string }): JSX.Element {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={cn("w-full", height)} />
      ))}
    </div>
  );
}

/** Errors explain what went wrong and how to fix it, in the interface's
 * voice. They never apologise and they are never vague. */
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }): JSX.Element {
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-[var(--radius-control)] bg-[hsl(var(--destructive-subtle))] p-3.5">
      <p className="text-xs font-medium text-[hsl(var(--status-error-fg))]">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

// ── Form fields ───────────────────────────────────────────────────────────

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-[hsl(var(--foreground-muted))]">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-[hsl(var(--foreground-muted))]">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-[var(--radius-control)] border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-2.5 text-sm text-[hsl(var(--foreground))] outline-none transition-shadow placeholder:text-[hsl(var(--foreground-muted))] focus:border-[hsl(var(--primary))] focus:ring-4 focus:ring-[hsl(var(--secondary))]";

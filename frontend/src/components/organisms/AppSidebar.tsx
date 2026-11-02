"use client";

/**
 * App sidebar -- Untitled UI "Sidebar navigation" style.
 *
 * Measurements and colours were taken from the reference design:
 *   296px wide, 16px side padding; brand lockup 32px mark + 22px bold name;
 *   section labels 12px / semibold / UPPERCASE / gray-500;
 *   nav rows 40px tall, 12px padding, 12px icon gap, 20px icons (gray-500),
 *   16px semibold gray-700 text; the active/hovered row is a gray-50 fill with
 *   darker (gray-800) text; counts are small bordered pills; chevrons gray-400;
 *   an account card at the bottom (40px avatar + green status dot, name, email,
 *   up/down chevron).
 * Everything is driven by the design tokens (--gray-*, --sidebar-*), so the
 * brand colour swap (UI-7) and dark mode need no changes here.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronsUpDown, LogOut, User as UserIcon } from "lucide-react";
import { cn } from "@/utils/cn";
import { useAuthStore } from "@/store/auth.store";
import { BrandMark } from "@/components/organization/BrandMark";

import {
  NAV_SECTIONS, filterSections, matchLength,
  type NavItem,
} from "@/config/navigation";

// The sidebar shows everyday pages only. Set-up / management pages (Departments,
// Shifts, Leave Types, Assets ...) live under Settings -> Management; the list of
// both is in "@/config/navigation".

/** The one sub-item that is "current": the most specific match among siblings,
 * so /devices/alerts highlights Activity Alerts but not also All Devices, and
 * /departments highlights Settings -> Management. */
function currentChildHref(children: NavItem[], pathname: string): string | null {
  let best: NavItem | null = null;
  let bestLen = 0;
  for (const c of children) {
    const len = matchLength(c, pathname);
    if (len > bestLen) { best = c; bestLen = len; }
  }
  return best?.href ?? null;
}

// ── Shared row styling ────────────────────────────────────────────────────────

const ROW =
  "group flex h-9 w-full items-center gap-3 rounded-md px-3 text-sm font-semibold " +
  "text-[hsl(var(--sidebar-foreground))] transition-colors " +
  "hover:bg-[hsl(var(--sidebar-hover))] hover:text-[hsl(var(--sidebar-active-fg))] " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]";
const ROW_ACTIVE = "bg-[hsl(var(--sidebar-active))] text-[hsl(var(--sidebar-active-fg))]";

export function AppSidebar() {
  const pathname = usePathname();
  const { user, hasPermission, logout } = useAuthStore();
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());

  const sections = filterSections(NAV_SECTIONS, hasPermission, !!user?.is_platform_admin);

  // Open the group that contains the current page (and keep whatever the user
  // opened or closed by hand otherwise).
  useEffect(() => {
    const toOpen: string[] = [];
    for (const s of filterSections(NAV_SECTIONS, hasPermission, !!user?.is_platform_admin)) {
      for (const item of s.items) {
        if (item.children && currentChildHref(item.children, pathname)) toOpen.push(item.label);
      }
    }
    if (toOpen.length) setOpenGroups(prev => new Set([...prev, ...toOpen]));
    // hasPermission is a stable store function; re-run when the route or user changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, user?.id]);

  function toggle(label: string) {
    setOpenGroups(prev => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  }

  return (
    <aside className="flex h-dvh w-[272px] shrink-0 flex-col border-r border-[hsl(var(--sidebar-border))] bg-[hsl(var(--sidebar-background))]">
      {/* Brand: the organization's logo, else the EWMP mark */}
      <BrandMark />

      {/* Navigation */}
      <nav aria-label="Main" className="sidebar-scroll flex-1 overflow-y-auto px-4 pb-4">
        {sections.map((section, i) => (
          <div key={section.label} className={cn(i > 0 && "mt-6")}>
            <p className="mb-1 px-1 text-xs font-semibold uppercase leading-[18px] text-[hsl(var(--sidebar-muted))]">
              {section.label}
            </p>
            <ul className="space-y-1">
              {section.items.map(item => (
                <li key={item.label}>
                  <NavRow
                    item={item}
                    pathname={pathname}
                    open={openGroups.has(item.label)}
                    onToggle={() => toggle(item.label)}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {/* Account */}
      <AccountCard
        name={user?.full_name ?? ""}
        email={user?.email ?? ""}
        avatarUrl={user?.avatar_url ?? null}
        initials={`${user?.first_name?.[0] ?? ""}${user?.last_name?.[0] ?? ""}`}
        onLogout={() => void logout()}
      />
    </aside>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex h-[22px] min-w-[22px] items-center justify-center rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--background))] px-1.5 text-sm font-medium text-[hsl(var(--sidebar-foreground))] shadow-[var(--shadow-xs)]">
      {children}
    </span>
  );
}

function NavRow({ item, pathname, open, onToggle }: {
  item: NavItem;
  pathname: string;
  open: boolean;
  onToggle: () => void;
}) {
  const Icon = item.icon;
  const iconEl = Icon ? (
    <Icon size={20} strokeWidth={1.75} className="shrink-0 text-[hsl(var(--sidebar-muted))]" aria-hidden />
  ) : null;

  if (item.children && item.children.length > 0) {
    const activeChild = currentChildHref(item.children, pathname);
    return (
      <div>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className={cn(ROW, activeChild && !open && ROW_ACTIVE)}
        >
          {iconEl}
          <span className="flex-1 text-left">{item.label}</span>
          {item.badge !== undefined && <Badge>{item.badge}</Badge>}
          <ChevronDown
            size={20}
            strokeWidth={1.75}
            aria-hidden
            className={cn("shrink-0 text-[hsl(var(--gray-400))] transition-transform", open && "rotate-180")}
          />
        </button>
        {open && (
          <ul className="mt-1 space-y-1">
            {item.children.map(child => (
              <li key={child.label}>
                <Link
                  href={child.href}
                  aria-current={activeChild === child.href ? "page" : undefined}
                  // Text lines up with the parent's label: 12px padding + 20px icon + 12px gap.
                  className={cn(ROW, "pl-11", activeChild === child.href && ROW_ACTIVE)}
                >
                  <span className="flex-1">{child.label}</span>
                  {child.badge !== undefined && <Badge>{child.badge}</Badge>}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const active = pathname === item.href || pathname.startsWith(item.href + "/");
  return (
    <Link href={item.href} aria-current={active ? "page" : undefined} className={cn(ROW, active && ROW_ACTIVE)}>
      {iconEl}
      <span className="flex-1">{item.label}</span>
      {item.badge !== undefined && <Badge>{item.badge}</Badge>}
    </Link>
  );
}

function AccountCard({ name, email, avatarUrl, initials, onLogout }: {
  name: string;
  email: string;
  avatarUrl: string | null;
  initials: string;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const item =
    "flex h-9 w-full items-center gap-2.5 rounded-md px-3 text-sm font-semibold text-[hsl(var(--sidebar-foreground))] " +
    "hover:bg-[hsl(var(--sidebar-hover))] hover:text-[hsl(var(--sidebar-active-fg))]";

  return (
    <div ref={ref} className="relative px-4 pb-4 pt-2">
      {open && (
        <div
          role="menu"
          className="absolute inset-x-4 bottom-full mb-2 rounded-xl border border-[hsl(var(--sidebar-border))] bg-[hsl(var(--background))] p-1 shadow-[var(--shadow-lg)]"
        >
          <Link href="/profile" role="menuitem" onClick={() => setOpen(false)} className={item}>
            <UserIcon size={16} aria-hidden /> My profile
          </Link>
          <button type="button" role="menuitem" onClick={onLogout} className={item}>
            <LogOut size={16} aria-hidden /> Log out
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-xl border border-[hsl(var(--sidebar-border))] bg-[hsl(var(--background))] p-3 text-left shadow-[var(--shadow-xs)] transition-colors hover:bg-[hsl(var(--sidebar-hover))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
      >
        <span className="relative shrink-0">
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={avatarUrl} alt="" className="h-10 w-10 rounded-full object-cover" />
          ) : (
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[hsl(var(--secondary))] text-sm font-semibold text-[hsl(var(--secondary-foreground))]">
              {initials}
            </span>
          )}
          <span
            aria-hidden
            className="absolute bottom-0 right-0 h-3 w-3 rounded-full border-2 border-[hsl(var(--background))] bg-[hsl(var(--success))]"
          />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold leading-5 text-[hsl(var(--foreground))]">{name}</span>
          <span className="block truncate text-sm leading-5 text-[hsl(var(--foreground-muted))]">{email}</span>
        </span>
        <ChevronsUpDown size={20} strokeWidth={1.75} aria-hidden className="shrink-0 text-[hsl(var(--gray-400))]" />
      </button>
    </div>
  );
}
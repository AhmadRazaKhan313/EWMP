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
import {
  BarChart3, Bot, Building2, CalendarDays, ChevronDown, ChevronsUpDown,
  CreditCard, DollarSign, Headphones, LayoutDashboard, LogOut,
  Monitor, Package, Plane, Settings, Shield, Store, TrendingUp,
  User as UserIcon, UserSearch, Users, Workflow,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/utils/cn";
import { useAuthStore } from "@/store/auth.store";

interface NavItem {
  label: string;
  href: string;
  /** Top-level rows have an icon; sub-items under a group do not. */
  icon?: LucideIcon;
  permission?: string;
  /** Visible if the user has ANY one of these — used for sections that have
   * both a manager-level and a self-service permission tier (e.g. Attendance:
   * "attendance.view" sees everyone, "attendance.view_own" sees only your
   * own). Checked in addition to `permission`, not instead of it. */
  anyPermission?: string[];
  platformAdminOnly?: boolean;
  badge?: string | number;
  children?: NavItem[];
}

interface NavSection {
  label: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    label: "General",
    items: [
      { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
      { label: "Employees", href: "/employees", icon: Users, permission: "employees.view" },
      {
        label: "Organization", href: "/departments", icon: Building2,
        children: [
          { label: "Departments",  href: "/departments",  permission: "departments.view" },
          { label: "Branches",     href: "/branches",     permission: "branches.manage" },
          { label: "Teams",        href: "/teams",        permission: "teams.manage" },
          { label: "Designations", href: "/designations", permission: "designations.manage" },
        ],
      },
      {
        label: "Attendance", href: "/attendance", icon: CalendarDays, permission: "attendance.view",
        anyPermission: ["attendance.view", "attendance.view_own"],
        children: [
          { label: "Daily Attendance", href: "/attendance", anyPermission: ["attendance.view", "attendance.view_own"] },
          { label: "Shifts",           href: "/shifts",     permission: "attendance.view" },
        ],
      },
      {
        label: "Leave", href: "/leave", icon: Plane, permission: "leave.view",
        anyPermission: ["leave.view", "leave.apply"],
        children: [
          { label: "Leave Requests", href: "/leave",       anyPermission: ["leave.view", "leave.apply"] },
          { label: "Leave Types",    href: "/leave-types", permission: "leave.manage_types" },
        ],
      },
    ],
  },
  {
    label: "Operations",
    items: [
      { label: "Payroll",     href: "/payroll",     icon: DollarSign, permission: "payroll.view" },
      { label: "Recruitment", href: "/recruitment", icon: UserSearch, permission: "recruitment.view" },
      { label: "Performance", href: "/performance", icon: TrendingUp, permission: "performance.view" },
      {
        label: "Devices", href: "/devices", icon: Monitor, permission: "devices.view",
        anyPermission: ["devices.view", "devices.view_alerts"],
        children: [
          { label: "All Devices",     href: "/devices",        permission: "devices.view" },
          { label: "Activity Alerts", href: "/devices/alerts", permission: "devices.view_alerts" },
        ],
      },
      { label: "Assets",   href: "/assets",   icon: Package,    permission: "assets.view" },
      { label: "Helpdesk", href: "/helpdesk", icon: Headphones, permission: "helpdesk.view" },
    ],
  },
  {
    label: "Tools",
    items: [
      { label: "Reports",      href: "/reports",          icon: BarChart3, permission: "reports.view" },
      { label: "AI Assistant", href: "/ai-assistant",     icon: Bot },
      { label: "Workflows",    href: "/workflow-builder", icon: Workflow,  permission: "workflows.view" },
      { label: "Marketplace",  href: "/marketplace",      icon: Store },
    ],
  },
  {
    label: "Admin",
    items: [
      { label: "Billing",       href: "/billing",     icon: CreditCard, permission: "billing.view" },
      { label: "Settings",      href: "/settings",    icon: Settings,   permission: "settings.view" },
      { label: "Organizations", href: "/admin-setup", icon: Shield,     platformAdminOnly: true },
    ],
  },
];

/**
 * Whether a single nav item (no children considered) is allowed for the
 * current user: platform-admin-only items need is_platform_admin; items
 * with no `permission` set are open to any authenticated user (matches
 * backend routes that only require get_current_user, e.g. org-structure
 * browsing, AI Assistant, Marketplace); everything else needs the
 * matching permission from the user's assigned role, or platform-admin
 * owner-bypass.
 */
function itemAllowed(
  item: NavItem,
  hasPermission: (permission: string) => boolean,
  isPlatformAdmin: boolean,
): boolean {
  if (item.platformAdminOnly) return isPlatformAdmin;
  if (!item.permission && !item.anyPermission) return true;
  if (isPlatformAdmin) return true;
  if (item.permission && hasPermission(item.permission)) return true;
  if (item.anyPermission && item.anyPermission.some(p => hasPermission(p))) return true;
  return false;
}

/**
 * Filters nav items down to what this user's role actually permits.
 * Children are filtered independently of their parent, so e.g. a role with
 * "leave.view" but not "leave.manage_types" sees "Leave Requests" but not
 * "Leave Types". A group whose parent permission check passes but ends up
 * with zero visible children is dropped entirely rather than showing an empty
 * expandable header.
 */
function filterNavItems(
  items: NavItem[],
  hasPermission: (permission: string) => boolean,
  isPlatformAdmin: boolean,
): NavItem[] {
  const result: NavItem[] = [];
  for (const item of items) {
    if (!itemAllowed(item, hasPermission, isPlatformAdmin)) continue;

    if (item.children && item.children.length > 0) {
      const visibleChildren = filterNavItems(item.children, hasPermission, isPlatformAdmin);
      if (visibleChildren.length > 0) {
        result.push({ ...item, children: visibleChildren });
      }
      continue;
    }

    result.push(item);
  }
  return result;
}

/** Sections with their items filtered; a section with nothing left is hidden. */
function filterSections(
  sections: NavSection[],
  hasPermission: (permission: string) => boolean,
  isPlatformAdmin: boolean,
): NavSection[] {
  return sections
    .map(s => ({ ...s, items: filterNavItems(s.items, hasPermission, isPlatformAdmin) }))
    .filter(s => s.items.length > 0);
}

/** The one sub-item that is "current": the longest matching href among siblings,
 * so /devices/alerts highlights Activity Alerts but not also All Devices. */
function currentChildHref(children: NavItem[], pathname: string): string | null {
  const matches = children
    .filter(c => pathname === c.href || pathname.startsWith(c.href + "/"))
    .sort((a, b) => b.href.length - a.href.length);
  return matches[0]?.href ?? null;
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
      {/* Brand */}
      <div className="flex items-center gap-2 px-5 pb-5 pt-5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[hsl(var(--sidebar-border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]">
          <Shield size={18} strokeWidth={2} className="text-[hsl(var(--primary))]" />
        </div>
        <span className="font-heading text-xl font-bold leading-8 tracking-tight text-[hsl(var(--foreground))]">
          EWMP
        </span>
      </div>

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
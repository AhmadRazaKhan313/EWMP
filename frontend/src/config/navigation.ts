/**
 * One source of truth for "which pages exist and who may see them".
 *
 * Used by:
 *   - AppSidebar            (the slim sidebar: everyday pages only)
 *   - Settings -> Management (the hub page: every set-up / management page)
 *   - CommandPalette        (Ctrl/Cmd+K search over all pages)
 *
 * To move a page between the sidebar and Settings -> Management, move its
 * entry between NAV_SECTIONS and MANAGEMENT_GROUPS below. Nothing else changes.
 */
import {
  BarChart3, Bot, Briefcase, Building2, CalendarDays, Clock, CreditCard, DollarSign,
  Headphones, LayoutDashboard, MapPin, Monitor, Package, Plane, Settings, Shield,
  Receipt, ShoppingCart, Store, TrendingUp, UserPlus, UserSearch, Users, Wallet, Workflow, type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  /** Top-level rows have an icon; sub-items under a group do not. */
  icon?: LucideIcon;
  permission?: string;
  /** Visible if the user has ANY one of these (checked in addition to `permission`). */
  anyPermission?: string[];
  platformAdminOnly?: boolean;
  /** Feature not finished yet. Hidden unless NEXT_PUBLIC_SHOW_INCOMPLETE=true. */
  incomplete?: boolean;
  badge?: string | number;
  /** Extra URL prefixes that make this row "current" (Settings -> Management is
   * current while you are on /departments, /shifts ...). */
  alsoActiveOn?: string[];
  /** One line shown on the Management page and in search. */
  description?: string;
  /** Extra search words (palette). */
  keywords?: string[];
  children?: NavItem[];
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

export const SHOW_INCOMPLETE = process.env.NEXT_PUBLIC_SHOW_INCOMPLETE === "true";

// ── Settings -> Management: every set-up / management page ──────────────────

export const MANAGEMENT_GROUPS: NavSection[] = [
  {
    label: "Organization",
    items: [
      { label: "Departments",  href: "/departments",  icon: Building2, permission: "departments.view",
        description: "Departments and who leads them.", keywords: ["dept", "structure"] },
      { label: "Branches",     href: "/branches",     icon: MapPin,    permission: "branches.manage",
        description: "Offices and locations.", keywords: ["office", "location"] },
      { label: "Teams",        href: "/teams",        icon: Users,     permission: "teams.manage",
        description: "Teams inside departments." },
      { label: "Designations", href: "/designations", icon: Briefcase, permission: "designations.manage",
        description: "Job titles.", keywords: ["job title", "role"] },
    ],
  },
  {
    label: "Attendance & Leave",
    items: [
      { label: "Shifts",      href: "/shifts",      icon: Clock,        permission: "attendance.view",
        description: "Working hours and night shifts.", keywords: ["timing", "schedule"] },
      { label: "Leave Types", href: "/leave-types", icon: CalendarDays, permission: "leave.manage_types",
        description: "Leave categories and yearly days.", keywords: ["holiday", "annual", "sick"] },
    ],
  },
  {
    label: "People & Assets",
    items: [
      { label: "Recruitment", href: "/recruitment", icon: UserSearch, permission: "recruitment.view",
        description: "Job openings and candidates.", keywords: ["hiring", "jobs", "candidates"] },
      { label: "Performance", href: "/performance", icon: TrendingUp, permission: "performance.view", incomplete: true,
        description: "Reviews and goals." },
      { label: "Assets",      href: "/assets",      icon: Package,    permission: "assets.view",
        description: "Company equipment given to employees.", keywords: ["laptop", "equipment"] },
    ],
  },
  {
    label: "Automation & Billing",
    items: [
      { label: "Workflows",   href: "/workflow-builder", icon: Workflow,   permission: "workflows.view", incomplete: true,
        description: "Automate approvals and reminders." },
      { label: "Marketplace", href: "/marketplace",      icon: Store,      incomplete: true,
        description: "Add-ons and integrations." },
      { label: "Billing",     href: "/billing",          icon: CreditCard, permission: "billing.view", incomplete: true,
        description: "Plan and invoices." },
    ],
  },
];

const MANAGEMENT_ITEMS: NavItem[] = MANAGEMENT_GROUPS.flatMap((g) => g.items);
export const MANAGEMENT_HREFS: string[] = MANAGEMENT_ITEMS.map((i) => i.href);
/** Anyone holding one of these can open the Management page. */
export const MANAGEMENT_PERMISSIONS: string[] = Array.from(
  new Set(MANAGEMENT_ITEMS.map((i) => i.permission).filter((p): p is string => !!p)),
);

// ── Sidebar: everyday pages only ─────────────────────────────────────────────

export const NAV_SECTIONS: NavSection[] = [
  {
    label: "General",
    items: [
      { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
      { label: "Employees", href: "/employees", icon: Users, permission: "employees.view" },
      { label: "Attendance", href: "/attendance", icon: CalendarDays, permission: "attendance.view",
        anyPermission: ["attendance.view", "attendance.view_own"] },
      { label: "Leave", href: "/leave", icon: Plane, permission: "leave.view",
        anyPermission: ["leave.view", "leave.apply"] },
    ],
  },
  {
    label: "Operations",
    items: [
      { label: "Payroll",    href: "/payroll",    icon: DollarSign, permission: "payroll.view" },
      { label: "Finance",    href: "/finance",    icon: Wallet,     permission: "finance.view" },
      { label: "Sales",      href: "/finance/sales", icon: Receipt, permission: "finance.view" },
      { label: "Purchases",  href: "/finance/purchases", icon: ShoppingCart, permission: "finance.view" },
      { label: "Finance Reports", href: "/finance/reports", icon: BarChart3, permission: "finance.view" },
      { label: "Onboarding", href: "/onboarding", icon: UserPlus,
        anyPermission: ["onboarding.view", "onboarding.view_own", "offers.manage", "offers.approve"] },
      {
        label: "Devices", href: "/devices", icon: Monitor, permission: "devices.view",
        anyPermission: ["devices.view", "devices.view_alerts"],
        children: [
          { label: "All Devices",     href: "/devices",        permission: "devices.view" },
          { label: "Activity Alerts", href: "/devices/alerts", permission: "devices.view_alerts" },
        ],
      },
      { label: "Helpdesk", href: "/helpdesk", icon: Headphones, permission: "helpdesk.view" },
    ],
  },
  {
    label: "Tools",
    items: [
      { label: "Reports",      href: "/reports",      icon: BarChart3, permission: "reports.view" },
      { label: "AI Assistant", href: "/ai-assistant", icon: Bot },
    ],
  },
  {
    label: "Admin",
    items: [
      {
        label: "Settings", href: "/settings", icon: Settings,
        anyPermission: ["settings.view", ...MANAGEMENT_PERMISSIONS],
        children: [
          { label: "General",    href: "/settings", permission: "settings.view" },
          { label: "Management", href: "/settings/management", anyPermission: MANAGEMENT_PERMISSIONS,
            alsoActiveOn: MANAGEMENT_HREFS },
        ],
      },
      { label: "Organizations", href: "/admin-setup", icon: Shield, platformAdminOnly: true },
    ],
  },
];

// ── Permission filtering (shared) ────────────────────────────────────────────

export type HasPermission = (permission: string) => boolean;

/** Whether a single item (children not considered) is allowed for this user. */
export function itemAllowed(item: NavItem, hasPermission: HasPermission, isPlatformAdmin: boolean): boolean {
  if (item.incomplete && !SHOW_INCOMPLETE) return false;
  if (item.platformAdminOnly) return isPlatformAdmin;
  if (!item.permission && !item.anyPermission) return true;
  if (isPlatformAdmin) return true;
  if (item.permission && hasPermission(item.permission)) return true;
  if (item.anyPermission && item.anyPermission.some((p) => hasPermission(p))) return true;
  return false;
}

/** Children are filtered independently; a group left with no children is dropped. */
export function filterNavItems(items: NavItem[], hasPermission: HasPermission, isPlatformAdmin: boolean): NavItem[] {
  const result: NavItem[] = [];
  for (const item of items) {
    if (!itemAllowed(item, hasPermission, isPlatformAdmin)) continue;
    if (item.children && item.children.length > 0) {
      const visible = filterNavItems(item.children, hasPermission, isPlatformAdmin);
      if (visible.length > 0) result.push({ ...item, children: visible });
      continue;
    }
    result.push(item);
  }
  return result;
}

/** Sections with their items filtered; an empty section is hidden. */
export function filterSections(sections: NavSection[], hasPermission: HasPermission, isPlatformAdmin: boolean): NavSection[] {
  return sections
    .map((s) => ({ ...s, items: filterNavItems(s.items, hasPermission, isPlatformAdmin) }))
    .filter((s) => s.items.length > 0);
}

/** Does `pathname` belong to this row? Returns the length of the best matching
 * prefix (0 = no match), so the most specific sibling wins. */
export function matchLength(item: NavItem, pathname: string): number {
  let best = 0;
  for (const href of [item.href, ...(item.alsoActiveOn ?? [])]) {
    if (pathname === href || pathname.startsWith(href + "/")) best = Math.max(best, href.length);
  }
  return best;
}

// ── Search (command palette) ─────────────────────────────────────────────────

export interface PageEntry {
  label: string;
  href: string;
  icon?: LucideIcon;
  group: string;
  description?: string;
  keywords?: string[];
}

/** Every page the user may open, for search. */
export function searchablePages(hasPermission: HasPermission, isPlatformAdmin: boolean): PageEntry[] {
  const pages: PageEntry[] = [];
  const seen = new Set<string>();
  const add = (item: NavItem, group: string) => {
    if (seen.has(item.href)) return;
    seen.add(item.href);
    pages.push({ label: item.label, href: item.href, icon: item.icon, group,
                 description: item.description, keywords: item.keywords });
  };
  for (const s of filterSections(NAV_SECTIONS, hasPermission, isPlatformAdmin)) {
    for (const item of s.items) {
      if (item.children?.length) {
        // The group row itself only opens/closes in the sidebar; search the real pages.
        for (const child of item.children) add({ ...child, icon: item.icon }, item.label);
      } else {
        add(item, s.label);
      }
    }
  }
  for (const g of filterSections(MANAGEMENT_GROUPS, hasPermission, isPlatformAdmin)) {
    for (const item of g.items) add(item, `Management · ${g.label}`);
  }
  add({ label: "My profile", href: "/profile", icon: Users, keywords: ["account", "password", "photo", "avatar"] }, "Account");
  return pages;
}

/** Rank pages for a typed query (higher = better; 0 = no match). */
export function scorePage(page: PageEntry, query: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 1;
  const label = page.label.toLowerCase();
  if (label === q) return 100;
  if (label.startsWith(q)) return 80;
  if (label.split(/\s+/).some((w) => w.startsWith(q))) return 60;
  if (label.includes(q)) return 40;
  if ((page.keywords ?? []).some((k) => k.toLowerCase().includes(q))) return 30;
  if ((page.description ?? "").toLowerCase().includes(q)) return 15;
  if (page.group.toLowerCase().includes(q)) return 10;
  return 0;
}

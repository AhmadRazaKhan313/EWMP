"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  LayoutDashboard, Users, Building2, GitBranch, CalendarDays, Plane,
  DollarSign, UserSearch, TrendingUp, Monitor, Package,
  Headphones, BarChart3, Settings, Bot, Workflow,
  Store, CreditCard, ChevronDown, ChevronRight,
  LogOut, Shield, Clock, Briefcase, Tag, MapPin,
} from "lucide-react";
import { cn } from "@/utils/cn";
import { useAuthStore } from "@/store/auth.store";

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
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

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard",      href: "/dashboard",        icon: <LayoutDashboard size={16}/> },
  { label: "Employees",      href: "/employees",        icon: <Users size={16}/>,       permission: "employees.view" },
  {
    label: "Organization", href: "/departments", icon: <Building2 size={16}/>,
    children: [
      { label: "Departments",  href: "/departments",   icon: <Building2 size={14}/>, permission: "departments.view" },
      { label: "Branches",     href: "/branches",      icon: <MapPin size={14}/>,    permission: "branches.manage" },
      { label: "Teams",        href: "/teams",         icon: <Users size={14}/>,     permission: "teams.manage" },
      { label: "Designations", href: "/designations",  icon: <Briefcase size={14}/>, permission: "designations.manage" },
    ],
  },
  {
    label: "Attendance", href: "/attendance", icon: <CalendarDays size={16}/>, permission: "attendance.view", anyPermission: ["attendance.view", "attendance.view_own"],
    children: [
      { label: "Daily Attendance", href: "/attendance",  icon: <CalendarDays size={14}/>, anyPermission: ["attendance.view", "attendance.view_own"] },
      { label: "Shifts",           href: "/shifts",      icon: <Clock size={14}/>,        permission: "attendance.view" },
    ],
  },
  {
    label: "Leave", href: "/leave", icon: <Plane size={16}/>, permission: "leave.view", anyPermission: ["leave.view", "leave.apply"],
    children: [
      { label: "Leave Requests", href: "/leave",       icon: <Plane size={14}/>, anyPermission: ["leave.view", "leave.apply"] },
      { label: "Leave Types",    href: "/leave-types", icon: <Tag size={14}/>,   permission: "leave.manage_types" },
    ],
  },
  { label: "Payroll",      href: "/payroll",          icon: <DollarSign size={16}/>, permission: "payroll.view" },
  { label: "Recruitment",  href: "/recruitment",      icon: <UserSearch size={16}/>, permission: "recruitment.view" },
  { label: "Performance",  href: "/performance",      icon: <TrendingUp size={16}/>, permission: "performance.view" },
  { label: "Devices",      href: "/devices",          icon: <Monitor size={16}/>,    permission: "devices.view" },
  { label: "Assets",       href: "/assets",           icon: <Package size={16}/>,    permission: "assets.view" },
  { label: "Helpdesk",     href: "/helpdesk",         icon: <Headphones size={16}/>, permission: "helpdesk.view" },
  { label: "Reports",      href: "/reports",          icon: <BarChart3 size={16}/>,  permission: "reports.view" },
  { label: "AI Assistant", href: "/ai-assistant",     icon: <Bot size={16}/> },
  { label: "Workflows",    href: "/workflow-builder", icon: <Workflow size={16}/>,   permission: "workflows.view" },
  { label: "Marketplace",  href: "/marketplace",      icon: <Store size={16}/> },
  { label: "Billing",      href: "/billing",          icon: <CreditCard size={16}/>, permission: "billing.view" },
  { label: "Settings",     href: "/settings",         icon: <Settings size={16}/>,   permission: "settings.view" },
  { label: "Organizations", href: "/admin-setup",      icon: <Shield size={16}/>, platformAdminOnly: true },
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
 * "Leave Types" — previously any child rendered unconditionally once the
 * parent's own permission passed. A group whose parent permission check
 * passes but ends up with zero visible children is dropped entirely
 * rather than showing an empty expandable header.
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

export function AppSidebar() {
  const pathname = usePathname();
  const { user, hasPermission, logout } = useAuthStore();
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set(["Organization", "Leave", "Attendance"]));

  function toggleExpanded(label: string) {
    setExpandedItems(prev => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  }

  function isActive(href: string) {
    return pathname === href || pathname.startsWith(href + "/");
  }

  const visibleItems = filterNavItems(NAV_ITEMS, hasPermission, !!user?.is_platform_admin);

  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col bg-[hsl(var(--sidebar-background))]">
      {/* Logo */}
      <div className="flex h-14 items-center gap-2.5 border-b border-[hsl(var(--sidebar-border))] px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/10">
          <Shield size={15} className="text-white"/>
        </div>
        <span className="font-heading text-[15px] font-semibold tracking-tight text-white">EWMP</span>
      </div>

      {/* Nav */}
      <nav className="sidebar-scroll flex-1 overflow-y-auto px-3 py-3">
        <div className="space-y-0.5">
          {visibleItems.map(item => (
            <NavItemRow
              key={item.label}
              item={item}
              isActive={isActive}
              isExpanded={expandedItems.has(item.label)}
              onToggle={() => toggleExpanded(item.label)}
            />
          ))}
        </div>
      </nav>

      {/* User footer */}
      <div className="border-t border-[hsl(var(--sidebar-border))] p-3">
        <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/15 text-xs font-semibold text-white">
            {user?.first_name?.[0]}{user?.last_name?.[0]}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium text-white">{user?.full_name}</p>
            <p className="truncate text-[11px] text-[hsl(var(--sidebar-muted))]">{user?.email}</p>
          </div>
          <button onClick={() => logout()} className="shrink-0 text-[hsl(var(--sidebar-muted))] hover:text-white transition-colors" title="Log out">
            <LogOut size={14}/>
          </button>
        </div>
      </div>
    </aside>
  );
}

function NavItemRow({ item, isActive, isExpanded, onToggle }: {
  item: NavItem;
  isActive: (href: string) => boolean;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const active = isActive(item.href);
  const hasChildren = item.children && item.children.length > 0;

  if (hasChildren) {
    const anyChildActive = item.children!.some(c => isActive(c.href));
    return (
      <div>
        <button
          onClick={onToggle}
          className={cn(
            "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium transition-colors",
            (active || anyChildActive)
              ? "bg-[hsl(var(--sidebar-active))] text-white"
              : "text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover))] hover:text-white",
          )}
        >
          <span className="shrink-0">{item.icon}</span>
          <span className="flex-1 text-left">{item.label}</span>
          <span className="shrink-0 text-[hsl(var(--sidebar-muted))]">
            {isExpanded ? <ChevronDown size={12}/> : <ChevronRight size={12}/>}
          </span>
        </button>
        {isExpanded && (
          <div className="ml-4 mt-0.5 space-y-0.5 border-l border-[hsl(var(--sidebar-border))] pl-3">
            {item.children!.map(child => (
              <Link
                key={child.label}
                href={child.href}
                className={cn(
                  "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[12.5px] transition-colors",
                  isActive(child.href)
                    ? "bg-[hsl(var(--sidebar-active))] text-white"
                    : "text-[hsl(var(--sidebar-muted))] hover:bg-[hsl(var(--sidebar-hover))] hover:text-white",
                )}
              >
                {child.icon}
                {child.label}
              </Link>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium transition-colors",
        active
          ? "bg-[hsl(var(--sidebar-active))] text-white"
          : "text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover))] hover:text-white",
      )}
    >
      <span className="shrink-0">{item.icon}</span>
      <span className="flex-1">{item.label}</span>
      {item.badge !== undefined && (
        <span className="rounded-full bg-white/20 px-1.5 py-0.5 text-[10px] font-semibold text-white">
          {item.badge}
        </span>
      )}
    </Link>
  );
}
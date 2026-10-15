"use client";

import { useState } from "react";
import { Bell, Search, ChevronsUpDown, ChevronRight, User, Settings, LogOut, ShieldAlert } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth.store";
import { useRecentDeviceAlerts } from "@/services/devices.service";

const PAGE_TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/employees": "Employees",
  "/departments": "Departments",
  "/branches": "Branches",
  "/teams": "Teams",
  "/attendance": "Attendance",
  "/leave": "Leave Management",
  "/payroll": "Payroll",
  "/recruitment": "Recruitment",
  "/performance": "Performance",
  "/devices": "Device Management",
  "/assets": "Asset Management",
  "/helpdesk": "IT Helpdesk",
  "/reports": "Reports & Analytics",
  "/ai-assistant": "AI Assistant",
  "/workflow-builder": "Workflow Builder",
  "/marketplace": "Marketplace",
  "/billing": "Billing",
  "/settings": "Settings",
  "/shifts": "Shifts",
  "/leave-types": "Leave Types",
  "/designations": "Designations",
  "/profile": "Profile",
  "/admin-setup": "Admin Setup",
};

function getPageTitle(pathname: string): string {
  for (const [path, title] of Object.entries(PAGE_TITLES)) {
    if (pathname === path || pathname.startsWith(path + "/")) {
      return title;
    }
  }
  return "EWMP";
}

export function AppTopbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const pageTitle = getPageTitle(pathname);

  return (
    <header className="flex h-16 shrink-0 items-center justify-between gap-4 bg-[hsl(var(--background))] px-8">
      {/* Left: breadcrumb — avatar and name, then the current page (Figma: page header) */}
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2">
        <span className="flex items-center gap-2 rounded-md px-2 py-1 text-sm font-semibold text-[hsl(var(--foreground-muted))]">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[hsl(var(--accent))] text-[10px] font-semibold text-[hsl(var(--accent-foreground))]">
            {user?.first_name?.[0]}{user?.last_name?.[0]}
          </span>
          <span className="hidden sm:inline">{user?.first_name} {user?.last_name}</span>
        </span>
        <ChevronRight size={16} className="shrink-0 text-[hsl(var(--gray-300))]" />
        <h1 className="truncate rounded-md bg-[hsl(var(--background-subtle))] px-2 py-1 font-heading text-sm font-semibold text-[hsl(var(--foreground-subtle))]">
          {pageTitle}
        </h1>
      </nav>

      {/* Right: Actions */}
      <div className="flex items-center gap-3">
        {/* Global search trigger */}
        <button className="flex h-10 w-64 items-center gap-2 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] px-3.5 text-sm text-[hsl(var(--foreground-muted))] shadow-[var(--shadow-xs)] transition-colors hover:border-[hsl(var(--brand-300))]">
          <Search size={18} />
          <span>Search</span>
          <span className="ml-auto rounded border border-[hsl(var(--border))] px-1.5 py-0.5 text-xs font-medium">
            ⌘K
          </span>
        </button>

        {/* Notifications */}
        <NotificationBell />

        {/* User menu */}
        <div className="group relative">
          <button className="flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] py-1.5 pl-2 pr-3 text-left shadow-[var(--shadow-xs)] transition-colors hover:bg-[hsl(var(--background-subtle))]">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[hsl(var(--accent))] text-xs font-semibold text-[hsl(var(--accent-foreground))]">
              {user?.first_name?.[0]}{user?.last_name?.[0]}
            </span>
            <span className="hidden min-w-0 sm:block">
              <span className="block truncate text-sm font-semibold leading-5 text-[hsl(var(--foreground-subtle))]">{user?.full_name || user?.first_name}</span>
              <span className="block max-w-[160px] truncate text-xs leading-[18px] text-[hsl(var(--foreground-muted))]">{user?.email}</span>
            </span>
            <ChevronsUpDown size={16} className="text-[hsl(var(--gray-400))]" />
          </button>

          {/* Dropdown */}
          <div className="absolute right-0 top-full z-50 mt-1 hidden w-56 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] py-1 shadow-lg group-hover:block">
            <div className="border-b border-[hsl(var(--border))] px-3 py-2">
              <p className="text-[13px] font-medium">{user?.full_name}</p>
              <p className="text-[11px] text-[hsl(var(--foreground-muted))]">{user?.email}</p>
            </div>
            <button
              onClick={() => router.push("/profile")}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-[13px] text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]"
            >
              <User size={13} /> Profile
            </button>
            <button
              onClick={() => router.push("/settings")}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-[13px] text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]"
            >
              <Settings size={13} /> Settings
            </button>
            <div className="border-t border-[hsl(var(--border))] mt-1 pt-1">
              <button
                onClick={() => logout()}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-[13px] text-[hsl(var(--destructive))] hover:bg-[hsl(var(--accent))]"
              >
                <LogOut size={13} /> Log out
              </button>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { data: alerts } = useRecentDeviceAlerts(120); // last 2 hours
  const unacknowledgedCount = (alerts ?? []).filter((a) => !a.is_acknowledged).length;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-10 w-10 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] transition-colors hover:bg-[hsl(var(--background-subtle))] hover:text-[hsl(var(--foreground))]"
      >
        <Bell size={20} />
        {unacknowledgedCount > 0 && (
          <span className="absolute right-1 top-1 flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-[hsl(var(--destructive))] px-0.5 text-[9px] font-bold text-white">
            {unacknowledgedCount > 9 ? "9+" : unacknowledgedCount}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-10 z-50 w-80 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-lg">
            <div className="border-b border-[hsl(var(--border))] px-4 py-3">
              <p className="text-sm font-semibold">Device Alerts</p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">Last 2 hours</p>
            </div>
            <div className="max-h-80 overflow-y-auto">
              {!alerts || alerts.length === 0 ? (
                <p className="px-4 py-6 text-center text-xs text-[hsl(var(--foreground-muted))]">
                  No recent alerts
                </p>
              ) : (
                alerts.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => {
                      setOpen(false);
                      router.push(`/devices?device_id=${a.device_id}&tab=alerts`);
                    }}
                    className="flex w-full items-start gap-2.5 border-b border-[hsl(var(--border))] px-4 py-2.5 text-left last:border-0 hover:bg-[hsl(var(--accent))]"
                  >
                    <ShieldAlert size={14} className="mt-0.5 shrink-0 text-[hsl(var(--warning))]" />
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium">{a.device_name}</p>
                      <p className="truncate text-xs text-[hsl(var(--foreground-muted))]">
                        {a.alert_type === "flagged_browsing" ? "Visited" : "Used"}: {a.detail}
                      </p>
                    </div>
                  </button>
                ))
              )}
            </div>
            <button
              onClick={() => {
                setOpen(false);
                router.push("/devices/alerts");
              }}
              className="w-full border-t border-[hsl(var(--border))] px-4 py-2.5 text-center text-xs font-medium text-[hsl(var(--primary))] hover:bg-[hsl(var(--accent))]"
            >
              View all alerts →
            </button>
          </div>
        </>
      )}
    </div>
  );
}
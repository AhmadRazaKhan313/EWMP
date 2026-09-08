"use client";

import { useState } from "react";
import { Bell, Search, ChevronDown, User, Settings, LogOut, ShieldAlert } from "lucide-react";
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
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-[hsl(var(--border))] bg-[hsl(var(--background))] px-6">
      {/* Left: Page title */}
      <h1 className="font-heading text-[15px] font-semibold text-[hsl(var(--foreground))]">
        {pageTitle}
      </h1>

      {/* Right: Actions */}
      <div className="flex items-center gap-2">
        {/* Global search trigger */}
        <button className="flex h-8 items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] px-3 text-[13px] text-[hsl(var(--foreground-muted))] transition-colors hover:border-[hsl(var(--border-strong))] hover:text-[hsl(var(--foreground))]">
          <Search size={13} />
          <span>Search...</span>
          <span className="ml-1 rounded border border-[hsl(var(--border))] px-1 py-0.5 text-[10px] font-mono">
            ⌘K
          </span>
        </button>

        {/* Notifications */}
        <NotificationBell />

        {/* User menu */}
        <div className="group relative">
          <button className="flex h-8 items-center gap-2 rounded-md px-2 text-[13px] font-medium text-[hsl(var(--foreground))] transition-colors hover:bg-[hsl(var(--accent))]">
            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[hsl(var(--primary))] text-[10px] font-bold text-[hsl(var(--primary-foreground))]">
              {user?.first_name?.[0]}{user?.last_name?.[0]}
            </div>
            <span className="hidden sm:inline">{user?.first_name}</span>
            <ChevronDown size={12} className="text-[hsl(var(--foreground-muted))]" />
          </button>

          {/* Dropdown */}
          <div className="absolute right-0 top-full z-50 mt-1 hidden w-48 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] py-1 shadow-lg group-hover:block">
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
        className="relative flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] transition-colors hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]"
      >
        <Bell size={15} />
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
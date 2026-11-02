"use client";

import { useEffect, useState } from "react";
import { Search, ChevronsUpDown, ChevronRight, User, Settings, LogOut } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth.store";
import { NotificationBell } from "./NotificationBell";
import { CommandPalette } from "./CommandPalette";

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
  "/settings/management": "Management",
  "/settings": "Settings",
  "/shifts": "Shifts",
  "/leave-types": "Leave Types",
  "/designations": "Designations",
  "/profile": "Profile",
  "/admin-setup": "Admin Setup",
};

function getPageTitle(pathname: string): string {
  // Most specific match wins (/settings/management before /settings).
  let best = "EWMP";
  let bestLen = 0;
  for (const [path, title] of Object.entries(PAGE_TITLES)) {
    if ((pathname === path || pathname.startsWith(path + "/")) && path.length > bestLen) {
      best = title;
      bestLen = path.length;
    }
  }
  return best;
}

export function AppTopbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const pageTitle = getPageTitle(pathname);

  // Global search: Ctrl+K / Cmd+K from anywhere, or click the Search box.
  const [searchOpen, setSearchOpen] = useState(false);
  const [shortcut, setShortcut] = useState("Ctrl K");
  useEffect(() => {
    if (/Mac|iPhone|iPad/i.test(navigator.platform)) setShortcut("⌘K");
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
        <button
          type="button"
          onClick={() => setSearchOpen(true)}
          aria-label="Search"
          className="flex h-10 w-64 items-center gap-2 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] px-3.5 text-sm text-[hsl(var(--foreground-muted))] shadow-[var(--shadow-xs)] transition-colors hover:border-[hsl(var(--brand-300))]"
        >
          <Search size={18} />
          <span>Search</span>
          <span className="ml-auto rounded border border-[hsl(var(--border))] px-1.5 py-0.5 text-xs font-medium">
            {shortcut}
          </span>
        </button>
        <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} />

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

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/utils/cn";

const tabs = [
  { href: "/payroll/dashboard", label: "Dashboard" },
  { href: "/payroll", label: "Payroll Runs" },
  { href: "/payroll/structures", label: "Salary Structures" },
  { href: "/payroll/compensation", label: "Compensation" },
  { href: "/payroll/tax", label: "Tax & Contributions" },
  { href: "/payroll/accounting", label: "Accounting" },
  { href: "/payroll/settings", label: "Settings" },
];

export function PayrollNav() {
  const pathname = usePathname();

  return (
    <div className="flex flex-wrap gap-3 border-b border-[hsl(var(--border))]">
      {tabs.map((tab) => {
        const isActive = tab.href === "/payroll" ? pathname === "/payroll" : pathname?.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              "px-1 pb-3 text-sm font-semibold border-b-2 -mb-px transition-colors",
              isActive
                ? "border-[hsl(var(--brand-600))] text-[hsl(var(--accent-foreground))]"
                : "border-transparent text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground-subtle))]",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}

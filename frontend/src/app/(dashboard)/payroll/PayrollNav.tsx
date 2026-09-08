"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/utils/cn";

const tabs = [
  { href: "/payroll", label: "Payroll Runs" },
  { href: "/payroll/structures", label: "Salary Structures" },
  { href: "/payroll/settings", label: "Settings" },
];

export function PayrollNav() {
  const pathname = usePathname();

  return (
    <div className="flex gap-1 border-b border-[hsl(var(--border))]">
      {tabs.map((tab) => {
        const isActive = tab.href === "/payroll" ? pathname === "/payroll" : pathname?.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              "px-3 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors",
              isActive
                ? "border-[hsl(var(--foreground))] text-[hsl(var(--foreground))]"
                : "border-transparent text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}

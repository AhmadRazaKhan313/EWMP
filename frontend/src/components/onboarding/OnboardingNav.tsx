"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuthStore } from "@/store/auth.store";
import { cn } from "@/utils/cn";

const ITEMS = [
  { href: "/onboarding", label: "Overview", perms: ["onboarding.view"], exact: true },
  { href: "/onboarding/offers", label: "Offers", perms: ["offers.manage", "offers.approve"] },
  { href: "/onboarding/cases", label: "Checklists", perms: ["onboarding.view"] },
  { href: "/onboarding/templates", label: "Templates", perms: ["onboarding.manage"] },
  { href: "/onboarding/tasks", label: "My tasks", perms: ["onboarding.view", "onboarding.view_own"] },
];

export function OnboardingNav() {
  const pathname = usePathname();
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const items = ITEMS.filter((i) => i.perms.some((p) => hasPermission(p)));
  return (
    <nav className="flex gap-1 border-b border-[hsl(var(--border))]" aria-label="Onboarding sections">
      {items.map((i) => {
        const active = i.exact ? pathname === i.href : pathname.startsWith(i.href);
        return (
          <Link key={i.href} href={i.href}
            className={cn("-mb-px border-b-2 px-3 py-2 text-sm font-semibold",
              active ? "border-[hsl(var(--primary))] text-[hsl(var(--primary))]"
                     : "border-transparent text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]")}>
            {i.label}
          </Link>
        );
      })}
    </nav>
  );
}

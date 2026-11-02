"use client";

/**
 * Settings -> Management: every set-up / management page in one place, so the
 * sidebar can stay short. Only pages the signed-in user may open are shown.
 */
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { useAuthStore } from "@/store/auth.store";
import { MANAGEMENT_GROUPS, filterSections } from "@/config/navigation";

export default function ManagementPage() {
  const { user, hasPermission } = useAuthStore();
  const groups = filterSections(MANAGEMENT_GROUPS, hasPermission, !!user?.is_platform_admin);

  return (
    <div className="mx-auto max-w-5xl space-y-8 px-8 pb-10">
      <p className="text-sm text-[hsl(var(--foreground-muted))]">
        Set up how your organization works. Everyday pages stay in the sidebar.
      </p>

      {groups.length === 0 ? (
        <p className="rounded-lg border border-dashed border-[hsl(var(--border))] px-4 py-10 text-center text-sm text-[hsl(var(--foreground-muted))]">
          You don&apos;t have access to any management pages.
        </p>
      ) : (
        groups.map((group) => (
          <section key={group.label} aria-labelledby={`mg-${group.label}`}>
            <h2
              id={`mg-${group.label}`}
              className="mb-3 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--foreground-muted))]"
            >
              {group.label}
            </h2>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className="group flex h-full items-start gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 shadow-[var(--shadow-xs)] transition-colors hover:border-[hsl(var(--brand-300))] hover:bg-[hsl(var(--background-subtle))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
                    >
                      {Icon && (
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]">
                          <Icon size={18} aria-hidden />
                        </span>
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-[hsl(var(--foreground))]">{item.label}</span>
                        {item.description && (
                          <span className="mt-0.5 block text-xs text-[hsl(var(--foreground-muted))]">{item.description}</span>
                        )}
                      </span>
                      <ChevronRight size={16} aria-hidden className="mt-1 shrink-0 text-[hsl(var(--gray-400))] transition-transform group-hover:translate-x-0.5" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}

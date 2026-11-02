"use client";

/**
 * Global search (Ctrl/Cmd+K): jump to any page the user may open, or find an
 * employee by name / code. Opened from the topbar's Search box.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CornerDownLeft, FileText, Search, User as UserIcon } from "lucide-react";
import apiClient from "@/services/api-client";
import { useAuthStore } from "@/store/auth.store";
import { cn } from "@/utils/cn";
import { scorePage, searchablePages } from "@/config/navigation";
import type { EmployeeListItem, PaginatedResponse } from "@/types";

interface Result {
  id: string;
  kind: "page" | "employee";
  label: string;
  hint: string;
  href: string;
  Icon: typeof FileText;
}

const MAX_PAGES = 8;
const MAX_EMPLOYEES = 6;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { user, hasPermission } = useAuthStore();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const q = query.trim();
  const debounced = useDebounced(q, 250);
  const canSearchPeople = hasPermission("employees.view");

  const employeesQuery = useQuery({
    queryKey: ["command-palette", "employees", debounced],
    queryFn: async () => {
      const { data } = await apiClient.get<PaginatedResponse<EmployeeListItem>>("/employees", {
        params: { query: debounced, page_size: MAX_EMPLOYEES },
      });
      return data.items;
    },
    enabled: open && canSearchPeople && debounced.length >= 2,
    staleTime: 30_000,
  });

  const pages = useMemo(
    () => searchablePages(hasPermission, !!user?.is_platform_admin),
    // hasPermission is a stable store function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [user?.id, user?.is_platform_admin],
  );

  const results: Result[] = useMemo(() => {
    const pageHits = pages
      .map((p) => ({ p, s: scorePage(p, q) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, MAX_PAGES)
      .map<Result>(({ p }) => ({
        id: `page:${p.href}`, kind: "page", label: p.label, hint: p.group, href: p.href, Icon: p.icon ?? FileText,
      }));
    // Only show employees that belong to the CURRENT text (not a stale earlier one).
    const people = debounced === q && q.length >= 2 ? employeesQuery.data ?? [] : [];
    const peopleHits = people.map<Result>((e) => ({
      id: `emp:${e.id}`, kind: "employee", label: e.full_name || `${e.first_name} ${e.last_name}`.trim(),
      hint: e.employee_code, href: `/employees/${e.id}`, Icon: UserIcon,
    }));
    return [...pageHits, ...peopleHits];
  }, [pages, q, debounced, employeesQuery.data]);

  // Fresh start every time it opens.
  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => setActive(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  function go(r: Result) {
    onClose();
    router.push(r.href);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => (results.length ? (i + 1) % results.length : 0)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => (results.length ? (i - 1 + results.length) % results.length : 0)); }
    else if (e.key === "Enter") { e.preventDefault(); const r = results[active]; if (r) go(r); }
  }

  const searchingPeople = canSearchPeople && q.length >= 2 && (debounced !== q || employeesQuery.isFetching);

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[12vh]" onKeyDown={onKeyDown}>
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search"
        className="relative w-full max-w-xl overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-lg"
      >
        <div className="flex items-center gap-2 border-b border-[hsl(var(--border))] px-4">
          <Search size={18} aria-hidden className="shrink-0 text-[hsl(var(--foreground-muted))]" />
          <input
            ref={inputRef}
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            role="combobox"
            aria-expanded="true"
            aria-controls="command-results"
            aria-activedescendant={results[active] ? `cmd-${results[active].id}` : undefined}
            aria-label="Search pages and employees"
            placeholder={canSearchPeople ? "Search pages or employees…" : "Search pages…"}
            autoComplete="off"
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-[hsl(var(--foreground-muted))]"
          />
          <kbd className="shrink-0 rounded border border-[hsl(var(--border))] px-1.5 py-0.5 text-[11px] text-[hsl(var(--foreground-muted))]">Esc</kbd>
        </div>

        <ul id="command-results" ref={listRef} role="listbox" className="max-h-80 overflow-y-auto py-1">
          {results.map((r, i) => (
            <li key={r.id} id={`cmd-${r.id}`} role="option" aria-selected={i === active}>
              <button
                type="button"
                onClick={() => go(r)}
                onMouseMove={() => setActive(i)}
                className={cn(
                  "flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm",
                  i === active ? "bg-[hsl(var(--accent))]" : "hover:bg-[hsl(var(--accent))]",
                )}
              >
                <r.Icon size={16} aria-hidden className="shrink-0 text-[hsl(var(--foreground-muted))]" />
                <span className="min-w-0 flex-1 truncate font-medium">{r.label}</span>
                <span className="shrink-0 text-xs text-[hsl(var(--foreground-muted))]">{r.hint}</span>
                {i === active && <CornerDownLeft size={14} aria-hidden className="shrink-0 text-[hsl(var(--foreground-muted))]" />}
              </button>
            </li>
          ))}
          {results.length === 0 && !searchingPeople && (
            <li className="px-4 py-8 text-center text-xs text-[hsl(var(--foreground-muted))]" role="presentation">
              No results for &ldquo;{q}&rdquo;
            </li>
          )}
          {searchingPeople && (
            <li className="px-4 py-2 text-center text-xs text-[hsl(var(--foreground-muted))]" role="presentation">
              Searching employees…
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}

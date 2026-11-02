"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { ColumnDef } from "@tanstack/react-table";
import { ClipboardList } from "lucide-react";
import { Badge, EmptyState, PageHeader } from "@/components/atoms";
import { DataTable } from "@/components/molecules/DataTable";
import { useCases, type OnboardingCase } from "@/services/onboarding.service";
import { ProgressBar, fmtDate } from "@/components/onboarding/ui";

const PAGE_SIZE = 20;
const STATUS = { pre_boarding: "Before day 1", active: "In progress", completed: "Completed", cancelled: "Cancelled" } as const;

export default function CasesPage() {
  const router = useRouter();
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const { data, isLoading } = useCases({ page: page + 1, page_size: PAGE_SIZE, search: search || undefined, kind: kind || undefined });

  const columns: ColumnDef<OnboardingCase, unknown>[] = [
    { header: "Employee", cell: ({ row }) => (
      <div><p className="text-sm font-medium">{row.original.employee.name}</p>
        <p className="text-xs text-[hsl(var(--foreground-muted))]">{row.original.employee.employee_code}</p></div>) },
    { header: "Type", accessorKey: "kind", cell: ({ getValue }) => <span className="text-sm capitalize">{getValue<string>()}</span> },
    { header: "Date", accessorKey: "anchor_date", cell: ({ getValue }) => fmtDate(getValue<string>()) },
    { header: "Progress", cell: ({ row }) => (
      <div className="w-40"><ProgressBar percent={row.original.progress.percent} />
        <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">
          {row.original.progress.done}/{row.original.progress.total}
          {row.original.progress.overdue > 0 && <span className="text-[hsl(var(--destructive))]"> · {row.original.progress.overdue} overdue</span>}
        </p></div>) },
    { header: "Status", accessorKey: "status", cell: ({ getValue }) => {
      const s = getValue<OnboardingCase["status"]>();
      return <Badge variant={s === "completed" ? "success" : s === "cancelled" ? "error" : "info"}>{STATUS[s]}</Badge>; } },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Checklists" description="Onboarding and offboarding for every employee." />
      <DataTable<OnboardingCase>
        data={data?.items ?? []} columns={columns} isLoading={isLoading} pageSize={PAGE_SIZE}
        searchPlaceholder="Search employee…"
        onRowClick={(c) => router.push(`/onboarding/cases/${c.id}`)}
        toolbar={
          <select aria-label="Filter by type" value={kind} onChange={(e) => { setKind(e.target.value); setPage(0); }}
                  className="h-10 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm">
            <option value="">All</option><option value="onboarding">Onboarding</option><option value="offboarding">Offboarding</option>
          </select>}
        emptyState={<EmptyState icon={ClipboardList} title="No checklists yet" description="Convert an accepted offer to start one." />}
        manual={{ pageIndex: page, pageCount: Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE)), totalRows: data?.total ?? 0,
                  onPageChange: setPage, searchValue: search, onSearchChange: (v) => { setSearch(v); setPage(0); } }}
      />
    </div>
  );
}

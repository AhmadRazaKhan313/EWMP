"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { ColumnDef } from "@tanstack/react-table";
import { FileText, Plus } from "lucide-react";
import { Button, EmptyState, PageHeader } from "@/components/atoms";
import { DataTable } from "@/components/molecules/DataTable";
import { useAuthStore } from "@/store/auth.store";
import { useOffers, type Offer } from "@/services/onboarding.service";
import { OfferStatusBadge, fmtDate } from "@/components/onboarding/ui";

const PAGE_SIZE = 20;

export default function OffersPage() {
  const router = useRouter();
  const canManage = useAuthStore((s) => s.hasPermission)("offers.manage");
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const { data, isLoading } = useOffers({ page: page + 1, page_size: PAGE_SIZE, search: search || undefined, status: status || undefined });

  const columns: ColumnDef<Offer, unknown>[] = [
    { header: "Candidate", accessorKey: "candidate_name", cell: ({ row }) => (
      <div><p className="text-sm font-medium">{row.original.candidate_name}</p>
        <p className="text-xs text-[hsl(var(--foreground-muted))]">{row.original.candidate_email}</p></div>) },
    { header: "Role", accessorKey: "job_title" },
    { header: "Joining", accessorKey: "joining_date", cell: ({ getValue }) => fmtDate(getValue<string>()) },
    { header: "Version", accessorKey: "version", cell: ({ getValue }) => `v${getValue<number>()}` },
    { header: "Status", accessorKey: "status", cell: ({ getValue }) => <OfferStatusBadge status={getValue<Offer["status"]>()} /> },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Offers" description="Create, approve and send offer letters; accepted offers become employees."
        action={canManage ? <Button icon={<Plus size={16} />} onClick={() => router.push("/onboarding/offers/new")}>New offer</Button> : undefined} />
      <DataTable<Offer>
        data={data?.items ?? []} columns={columns} isLoading={isLoading}
        searchPlaceholder="Search candidate or role…"
        onRowClick={(o) => router.push(`/onboarding/offers/${o.id}`)}
        toolbar={
          <select aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}
                  className="h-10 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm">
            <option value="">All statuses</option>
            {["draft", "pending_approval", "approved", "sent", "viewed", "accepted", "declined", "expired", "revoked"].map((s) => (
              <option key={s} value={s}>{s.replace("_", " ")}</option>))}
          </select>}
        emptyState={<EmptyState icon={FileText} title="No offers yet" description="Create the first offer to start hiring." />}
        pageSize={PAGE_SIZE}
        manual={{ pageIndex: page, pageCount: Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE)), totalRows: data?.total ?? 0,
                  onPageChange: setPage, searchValue: search, onSearchChange: (v) => { setSearch(v); setPage(0); } }}
      />
    </div>
  );
}

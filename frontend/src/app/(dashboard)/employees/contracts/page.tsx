"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, FileText } from "lucide-react";
import { Button, Card, EmptyState, PageHeader, Skeleton } from "@/components/atoms";
import { ContractStateBadge, typeLabel } from "@/components/employee/ContractsPanel";
import { useContracts } from "@/services/employeeLifecycle.service";

const FILTERS = [
  { value: "", label: "All" },
  { value: "expiring", label: "Expiring soon" },
  { value: "expired", label: "Expired" },
  { value: "active", label: "Active" },
  { value: "renewed", label: "Renewed" },
  { value: "terminated", label: "Terminated" },
];
const fmt = (d: string | null) =>
  d ? new Date(d).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" }) : "—";

/** Every contract in the organisation; "Expiring soon" is the renewal to-do list. */
export default function ContractsPage() {
  const [state, setState] = useState("expiring");
  const [page, setPage] = useState(1);
  const { data, isLoading } = useContracts({ state: state || undefined, page, page_size: 25 });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Contracts"
        description="Track contract end dates and renew them before they lapse."
        action={<Link href="/employees"><Button variant="outline" icon={<ArrowLeft size={14} />}>Employees</Button></Link>}
      />
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Contract filter">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            role="tab"
            aria-selected={state === f.value}
            onClick={() => { setState(f.value); setPage(1); }}
            className={
              "rounded-full border px-3 py-1 text-xs font-medium " +
              (state === f.value
                ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                : "border-[hsl(var(--border))] hover:bg-[hsl(var(--accent))]")
            }
          >
            {f.label}
          </button>
        ))}
      </div>
      <Card padding={false}>
        {isLoading ? (
          <div className="p-5"><Skeleton className="h-24 w-full" /></div>
        ) : !data?.items.length ? (
          <EmptyState icon={FileText} title="No contracts here" description="Contracts added on an employee's Contract tab appear in this list." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--foreground-muted))]">
                <th className="px-5 py-3 font-medium">Employee</th>
                <th className="px-3 py-3 font-medium">Type</th>
                <th className="px-3 py-3 font-medium">Start</th>
                <th className="px-3 py-3 font-medium">End</th>
                <th className="px-3 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id} className="border-b border-[hsl(var(--border))] last:border-0">
                  <td className="px-5 py-3">
                    <Link href={`/employees/${c.employee_id}?tab=contract`} className="font-medium hover:underline">{c.employee_name}</Link>
                    <p className="font-mono text-[11px] text-[hsl(var(--foreground-muted))]">{c.employee_code}</p>
                  </td>
                  <td className="px-3 py-3">{typeLabel(c.contract_type)}</td>
                  <td className="px-3 py-3">{fmt(c.start_date)}</td>
                  <td className="px-3 py-3">{fmt(c.end_date)}</td>
                  <td className="px-3 py-3"><ContractStateBadge contract={c} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {data && data.total_pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <span>Page {page} of {data.total_pages}</span>
          <Button size="sm" variant="outline" disabled={page >= data.total_pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </div>
  );
}

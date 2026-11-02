"use client";

import { History } from "lucide-react";
import { Card, Skeleton } from "@/components/atoms";
import { useEmployeeHistory } from "@/services/employeeLifecycle.service";

const label = (s: string | null) => (s ? s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "New hire");
const SOURCE: Record<string, string> = {
  created: "Joined", update: "Edited", offboard: "Offboarded", import: "Imported",
};

/** Employment-status timeline (newest first). */
export function StatusTimeline({ employeeId }: { employeeId: string }) {
  const { data, isLoading } = useEmployeeHistory(employeeId);
  return (
    <Card padding={false}>
      <div className="flex items-center gap-2 border-b border-[hsl(var(--border))] px-5 py-4">
        <History size={15} className="text-[hsl(var(--foreground-subtle))]" />
        <h3 className="font-heading text-sm font-semibold">Status history</h3>
      </div>
      <div className="px-5 py-4" data-testid="status-timeline">
        {isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : !data?.length ? (
          <p className="text-sm text-[hsl(var(--foreground-muted))]">No status changes recorded yet.</p>
        ) : (
          <ol className="space-y-4 border-l border-[hsl(var(--border))] pl-4">
            {data.map((h) => (
              <li key={h.id} className="relative">
                <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-[hsl(var(--primary))]" />
                <p className="text-sm font-medium">
                  {h.from_status ? `${label(h.from_status)} → ${label(h.to_status)}` : label(h.to_status)}
                  <span className="ml-2 text-xs font-normal text-[hsl(var(--foreground-muted))]">{SOURCE[h.source] ?? h.source}</span>
                </p>
                <p className="text-xs text-[hsl(var(--foreground-muted))]">
                  {new Date(h.effective_date).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" })}
                  {h.changed_by ? ` · by ${h.changed_by}` : ""}
                </p>
                {h.reason && <p className="mt-0.5 text-xs">{h.reason}</p>}
              </li>
            ))}
          </ol>
        )}
      </div>
    </Card>
  );
}

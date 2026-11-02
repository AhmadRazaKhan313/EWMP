"use client";
import { useState } from "react";
import Link from "next/link";
import { ListChecks } from "lucide-react";
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from "@/components/atoms";
import { useMyTasks, useUpdateTask } from "@/services/onboarding.service";
import { TASK_STATUS, fmtDate } from "@/components/onboarding/ui";

export default function MyTasksPage() {
  const [showDone, setShowDone] = useState(false);
  const { data, isLoading } = useMyTasks(showDone);
  const update = useUpdateTask();
  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader title="My tasks" description="Onboarding and offboarding steps assigned to you or your team."
        action={<label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> Show completed</label>} />
      {isLoading && <Skeleton className="h-32 w-full" />}
      {data && data.length === 0 && <Card><EmptyState icon={ListChecks} title="You're all caught up" description="No open onboarding tasks." /></Card>}
      <ul className="space-y-3">
        {data?.map((t) => (
          <li key={t.id}>
            <Card>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium">{t.title}</p>
                  <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
                    <Link className="underline" href={`/onboarding/cases/${t.case.id}`}>Open checklist</Link> · due {fmtDate(t.due_date)}
                    {t.blocked && " · waiting on an earlier step"}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {t.overdue && t.status !== "done" && <Badge variant="error">Overdue</Badge>}
                  <Badge variant={TASK_STATUS[t.status].variant}>{TASK_STATUS[t.status].label}</Badge>
                  {t.status !== "done" && !t.blocked && (
                    <Button size="sm" disabled={update.isPending} onClick={() => update.mutate({ id: t.id, status: "done" })}>Done</Button>)}
                </div>
              </div>
            </Card>
          </li>))}
      </ul>
    </div>
  );
}

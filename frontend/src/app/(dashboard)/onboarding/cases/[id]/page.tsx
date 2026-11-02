"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import { Badge, Button, Card, CardHeader, PageHeader, Skeleton } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import {
  PHASES, useCancelCase, useCase, useConfirmCase, useNewPreboardingLink, useReviewDocument,
  useSendWelcome, useUpdateTask, type CaseTask,
} from "@/services/onboarding.service";
import { ProgressBar, TASK_STATUS, fmtDate, inputCls } from "@/components/onboarding/ui";

function TaskRow({ t, canManage }: { t: CaseTask; canManage: boolean }) {
  const update = useUpdateTask();
  const st = TASK_STATUS[t.status];
  return (
    <li className="flex items-start justify-between gap-3 px-6 py-3">
      <div className="min-w-0">
        <p className={t.status === "done" ? "text-sm text-[hsl(var(--foreground-muted))] line-through" : "text-sm font-medium"}>{t.title}</p>
        <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
          {t.owner_role.toUpperCase()}{t.assignee_name ? ` · ${t.assignee_name}` : ""} · due {fmtDate(t.due_date)}
          {t.blocked && " · waiting on an earlier step"}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {t.overdue && t.status !== "done" && <Badge variant="error">Overdue</Badge>}
        <Badge variant={st.variant}>{st.label}</Badge>
        {canManage && t.status !== "done" && t.kind === "manual" && !t.blocked && (
          <Button size="sm" variant="secondary" disabled={update.isPending}
                  onClick={() => update.mutate({ id: t.id, status: "done" })}>Mark done</Button>)}
      </div>
    </li>
  );
}

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const has = useAuthStore((s) => s.hasPermission);
  const canManage = has("onboarding.manage");
  const { data: c, isLoading } = useCase(id);
  const welcome = useSendWelcome(id);
  const confirm = useConfirmCase(id);
  const cancel = useCancelCase(id);
  const newLink = useNewPreboardingLink(id);
  const review = useReviewDocument();
  const [message, setMessage] = useState("");
  const [link, setLink] = useState<string | null>(null);

  if (isLoading || !c) return <Skeleton className="h-64 w-full" />;
  const open = c.status === "pre_boarding" || c.status === "active";

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader title={c.employee.name}
        description={`${c.kind === "onboarding" ? "Joining" : "Last day"} ${fmtDate(c.anchor_date)} · ${c.progress.done}/${c.progress.total} done`}
        action={<Badge variant={c.status === "completed" ? "success" : "info"}>{c.status.replace("_", " ")}</Badge>} />
      <ProgressBar percent={c.progress.percent} />

      {canManage && open && c.kind === "onboarding" && (
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" disabled={newLink.isPending}
                  onClick={() => newLink.mutate(undefined, { onSuccess: (r) => setLink(r.link) })}>New pre-boarding link</Button>
          <Button variant="secondary" disabled={confirm.isPending} onClick={() => confirm.mutate({})}>Confirm employee (end probation)</Button>
          <Button variant="destructive" disabled={cancel.isPending} onClick={() => cancel.mutate()}>Cancel checklist</Button>
        </div>)}
      {link && (
        <Card><p className="text-sm font-medium">Pre-boarding link (shown only now)</p>
          <input readOnly className={`${inputCls} mt-2 font-mono`} value={link} onFocus={(e) => e.currentTarget.select()} /></Card>)}

      {PHASES.map((p) => {
        const tasks = (c.tasks ?? []).filter((t) => t.phase === p.value);
        if (tasks.length === 0) return null;
        return (
          <Card key={p.value} padding={false}>
            <CardHeader title={p.label} />
            <ul className="divide-y divide-[hsl(var(--border))]">{tasks.map((t) => <TaskRow key={t.id} t={t} canManage={canManage} />)}</ul>
          </Card>);
      })}

      {(c.documents?.length ?? 0) > 0 && (
        <Card padding={false}>
          <CardHeader title="Documents from the new hire" />
          <ul className="divide-y divide-[hsl(var(--border))]">
            {c.documents!.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-3 px-6 py-3 text-sm">
                <span>{d.title}{d.is_required && " *"}</span>
                <div className="flex items-center gap-2">
                  <Badge variant={d.status === "verified" ? "success" : d.status === "rejected" ? "error" : "default"}>{d.status}</Badge>
                  {canManage && d.status === "uploaded" && (<>
                    <Button size="sm" variant="secondary" onClick={() => review.mutate({ id: d.id, approve: true })}>Verify</Button>
                    <Button size="sm" variant="ghost" onClick={() => {
                      const reason = window.prompt("Why is it rejected?");
                      if (reason) review.mutate({ id: d.id, approve: false, reason });
                    }}>Reject</Button></>)}
                </div>
              </li>))}
          </ul>
        </Card>)}

      {canManage && open && c.kind === "onboarding" && (
        <Card>
          <h3 className="font-heading text-base font-semibold">Welcome message</h3>
          <textarea className={`${inputCls} mt-3 min-h-24`} placeholder="A short personal note (optional)" value={message} onChange={(e) => setMessage(e.target.value)} />
          <div className="mt-3"><Button disabled={welcome.isPending} onClick={() => welcome.mutate(message || null)}>
            {c.welcome_sent_at ? "Send again" : "Send welcome"}</Button></div>
        </Card>)}
    </div>
  );
}

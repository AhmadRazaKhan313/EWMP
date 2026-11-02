"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button, Card, PageHeader, Skeleton } from "@/components/atoms";
import {
  OWNER_ROLES, PHASES, TASK_KINDS, useSaveTemplate, useTemplate,
  type OwnerRole, type TaskKind, type TaskPhase, type TemplateTask,
} from "@/services/onboarding.service";
import { Field, inputCls } from "@/components/onboarding/ui";

const blank = (order: number): TemplateTask => ({
  order, title: "", description: null, owner_role: "hr", phase: "day_1", due_offset_days: 0,
  depends_on_order: null, is_required: true, kind: "manual", provision_key: null, link_url: null,
});

export default function TemplateEditorPage() {
  const { id } = useParams<{ id: string }>();
  const isNew = id === "new";
  const router = useRouter();
  const { data, isLoading } = useTemplate(id);
  const save = useSaveTemplate(isNew ? null : id);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<"onboarding" | "offboarding">("onboarding");
  const [isDefault, setIsDefault] = useState(false);
  const [tasks, setTasks] = useState<TemplateTask[]>([blank(1)]);

  useEffect(() => {
    if (!data) return;
    setName(data.name); setDescription(data.description ?? ""); setKind(data.kind); setIsDefault(data.is_default);
    setTasks((data.tasks ?? []).map((t) => ({ ...t })));
  }, [data]);

  if (!isNew && isLoading) return <Skeleton className="h-64 w-full" />;

  const patch = (i: number, p: Partial<TemplateTask>) => setTasks((ts) => ts.map((t, j) => (j === i ? { ...t, ...p } : t)));
  const remove = (i: number) => setTasks((ts) => {
    const gone = ts[i]!.order;
    const rest = ts.filter((_, j) => j !== i);
    const map = new Map(rest.map((t, j) => [t.order, j + 1]));
    return rest.map((t, j) => ({ ...t, order: j + 1, depends_on_order: t.depends_on_order && t.depends_on_order !== gone ? (map.get(t.depends_on_order) ?? null) : null }));
  });
  const valid = name.trim().length > 0 && tasks.length > 0 && tasks.every((t) => t.title.trim());

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    save.mutate({ name: name.trim(), description: description || null, kind, is_default: isDefault,
      tasks: tasks.map((t, i) => ({ ...t, order: i + 1, title: t.title.trim() })) },
      { onSuccess: () => router.push("/onboarding/templates") });
  };

  return (
    <form onSubmit={submit} className="max-w-4xl space-y-6">
      <PageHeader title={isNew ? "New template" : "Edit template"} />
      <Card>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required /></Field>
          <Field label="Type">
            <select className={inputCls} value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} disabled={!isNew}>
              <option value="onboarding">Onboarding</option><option value="offboarding">Offboarding</option></select></Field>
          <div className="sm:col-span-2"><Field label="Description">
            <input className={inputCls} value={description} onChange={(e) => setDescription(e.target.value)} /></Field></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} /> Use as the default for this type</label>
        </div>
      </Card>

      <div className="space-y-3">
        {tasks.map((t, i) => (
          <Card key={i}>
            <div className="grid gap-3 sm:grid-cols-6">
              <div className="sm:col-span-6"><Field label={`Step ${i + 1}`}>
                <input className={inputCls} value={t.title} onChange={(e) => patch(i, { title: e.target.value })} placeholder="What needs to happen?" /></Field></div>
              <div className="sm:col-span-2"><Field label="Owner">
                <select className={inputCls} value={t.owner_role} onChange={(e) => patch(i, { owner_role: e.target.value as OwnerRole })}>
                  {OWNER_ROLES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></Field></div>
              <div className="sm:col-span-2"><Field label="When">
                <select className={inputCls} value={t.phase} onChange={(e) => patch(i, { phase: e.target.value as TaskPhase })}>
                  {PHASES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></Field></div>
              <div className="sm:col-span-2"><Field label="Due (days from date)" hint="Negative = before.">
                <input type="number" className={inputCls} value={t.due_offset_days} onChange={(e) => patch(i, { due_offset_days: Number(e.target.value) || 0 })} /></Field></div>
              <div className="sm:col-span-3"><Field label="Kind">
                <select className={inputCls} value={t.kind} onChange={(e) => patch(i, { kind: e.target.value as TaskKind })}>
                  {TASK_KINDS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></Field></div>
              <div className="sm:col-span-3"><Field label="After step">
                <select className={inputCls} value={t.depends_on_order ?? ""} onChange={(e) => patch(i, { depends_on_order: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">—</option>
                  {tasks.slice(0, i).map((p, j) => <option key={j} value={j + 1}>{j + 1}. {p.title || "Untitled"}</option>)}</select></Field></div>
              <label className="flex items-center gap-2 text-sm sm:col-span-4"><input type="checkbox" checked={t.is_required} onChange={(e) => patch(i, { is_required: e.target.checked })} /> Required</label>
              <div className="text-right sm:col-span-2">
                <Button variant="ghost" size="sm" onClick={() => remove(i)} disabled={tasks.length === 1}>Remove</Button></div>
            </div>
          </Card>))}
        <Button variant="secondary" onClick={() => setTasks((ts) => [...ts, blank(ts.length + 1)])}>Add a step</Button>
      </div>

      <div className="flex gap-3">
        <Button type="submit" disabled={!valid || save.isPending}>{save.isPending ? "Saving…" : "Save template"}</Button>
        <Button variant="secondary" onClick={() => router.push("/onboarding/templates")}>Cancel</Button>
      </div>
    </form>
  );
}

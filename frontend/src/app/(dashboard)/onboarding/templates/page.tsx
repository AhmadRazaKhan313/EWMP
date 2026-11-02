"use client";
import Link from "next/link";
import { LayoutTemplate, Plus } from "lucide-react";
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from "@/components/atoms";
import { useDeleteTemplate, useSeedTemplates, useTemplates } from "@/services/onboarding.service";

export default function TemplatesPage() {
  const { data, isLoading } = useTemplates();
  const seed = useSeedTemplates();
  const del = useDeleteTemplate();
  return (
    <div className="space-y-6">
      <PageHeader title="Templates" description="Checklists that are copied to each new joiner or leaver."
        action={<div className="flex gap-3">
          <Button variant="secondary" disabled={seed.isPending} onClick={() => seed.mutate()}>Add default templates</Button>
          <Link href="/onboarding/templates/new"><Button icon={<Plus size={16} />}>New template</Button></Link>
        </div>} />
      {isLoading && <Skeleton className="h-32 w-full" />}
      {data && data.length === 0 && (
        <Card><EmptyState icon={LayoutTemplate} title="No templates yet" description="Start from the ready-made onboarding and offboarding checklists." /></Card>)}
      <div className="grid gap-4 md:grid-cols-2">
        {data?.map((t) => (
          <Card key={t.id}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <Link href={`/onboarding/templates/${t.id}`} className="font-medium hover:underline">{t.name}</Link>
                <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">{t.task_count ?? 0} steps · {t.kind}</p>
              </div>
              <div className="flex items-center gap-2">
                {t.is_default && <Badge variant="info">Default</Badge>}
                {!t.is_active && <Badge variant="default">Inactive</Badge>}
              </div>
            </div>
            <div className="mt-4">
              <Button size="sm" variant="ghost" disabled={del.isPending}
                      onClick={() => { if (window.confirm(`Delete “${t.name}”?`)) del.mutate(t.id); }}>Delete</Button>
            </div>
          </Card>))}
      </div>
    </div>
  );
}

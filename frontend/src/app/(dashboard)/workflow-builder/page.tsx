import { PageHeader } from "@/components/atoms";
export default function Page() {
  return (
    <div className="space-y-6">
      <PageHeader title="Coming Soon" description="This module is in active development." />
      <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-[hsl(var(--border))] text-sm text-[hsl(var(--foreground-muted))]">
        Module under construction — check back soon
      </div>
    </div>
  );
}

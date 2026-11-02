"use client";
import Link from "next/link";
import { AlertTriangle, CalendarClock, CheckCircle2, UserPlus, UserMinus } from "lucide-react";
import { Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/atoms";
import { useOnboardingDashboard } from "@/services/onboarding.service";
import { ProgressBar, fmtDate } from "@/components/onboarding/ui";

function Stat({ label, value, icon: Icon, tone }: { label: string; value: number; icon: React.ElementType; tone?: "warn" }) {
  return (
    <Card>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-[hsl(var(--foreground-muted))]">{label}</p>
          <p className={tone === "warn" && value > 0 ? "mt-1 text-3xl font-semibold text-[hsl(var(--destructive))]" : "mt-1 text-3xl font-semibold"}>{value}</p>
        </div>
        <Icon size={22} className="text-[hsl(var(--foreground-muted))]" />
      </div>
    </Card>
  );
}

export default function OnboardingOverviewPage() {
  const { data, isLoading, isError } = useOnboardingDashboard();
  return (
    <div className="space-y-6">
      <PageHeader title="Onboarding" description="Offers, new joiners and exits in one place." />
      {isLoading && <Skeleton className="h-40 w-full" />}
      {isError && <p className="text-sm text-[hsl(var(--destructive))]">Could not load the overview.</p>}
      {data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <Stat label="Onboarding in progress" value={data.totals.open_onboarding} icon={UserPlus} />
            <Stat label="Offboarding in progress" value={data.totals.open_offboarding} icon={UserMinus} />
            <Stat label="Overdue tasks" value={data.totals.overdue_tasks} icon={AlertTriangle} tone="warn" />
            <Stat label="Due this week" value={data.totals.due_this_week} icon={CalendarClock} />
            <Stat label="Completed this month" value={data.totals.completed_this_month} icon={CheckCircle2} />
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card padding={false}>
              <CardHeader title="Upcoming joiners" />
              {data.upcoming_joiners.length === 0 ? (
                <EmptyState icon={UserPlus} title="No joiners coming up" description="Convert an accepted offer to start a checklist." />
              ) : (
                <ul className="divide-y divide-[hsl(var(--border))]">
                  {data.upcoming_joiners.map((c) => (
                    <li key={c.id}>
                      <Link href={`/onboarding/cases/${c.id}`} className="block px-6 py-4 hover:bg-[hsl(var(--background-subtle))]">
                        <div className="flex items-center justify-between text-sm">
                          <span className="font-medium">{c.employee.name}</span>
                          <span className="text-[hsl(var(--foreground-muted))]">
                            {c.days_until > 0 ? `in ${c.days_until} days` : c.days_until === 0 ? "today" : fmtDate(c.anchor_date)}
                          </span>
                        </div>
                        <div className="mt-2"><ProgressBar percent={c.progress.percent} /></div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card padding={false}>
              <CardHeader title="Where things are stuck" description="Overdue tasks grouped by owner and step." />
              <div className="space-y-5 p-6 text-sm">
                {data.bottlenecks.by_owner_role.length === 0 && data.bottlenecks.by_task.length === 0 ? (
                  <p className="text-[hsl(var(--foreground-muted))]">Nothing is overdue. 🎉</p>
                ) : (
                  <>
                    <div>
                      <p className="mb-2 font-medium">By owner</p>
                      {data.bottlenecks.by_owner_role.map((b) => (
                        <div key={b.owner_role} className="flex justify-between py-0.5">
                          <span className="capitalize">{b.owner_role}</span><span className="font-mono">{b.overdue}</span>
                        </div>
                      ))}
                    </div>
                    <div>
                      <p className="mb-2 font-medium">Slowest steps</p>
                      {data.bottlenecks.by_task.map((b) => (
                        <div key={b.title} className="flex justify-between py-0.5">
                          <span>{b.title}</span><span className="font-mono">{b.overdue}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

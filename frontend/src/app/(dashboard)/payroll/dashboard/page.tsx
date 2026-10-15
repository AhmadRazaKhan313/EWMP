"use client";

import { useRouter } from "next/navigation";
import { Users, Clock, TrendingUp, CalendarClock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import apiClient from "@/services/api-client";
import { Badge, Card, PageHeader } from "@/components/atoms";
import { PayrollNav } from "../PayrollNav";

interface DashboardData {
  total_employees_on_payroll: number;
  current_run: { id: string; name: string; status: string; total_gross: string; total_net: string } | null;
  pending_approvals: number;
  upcoming_pay_date: string | null;
  cost_trend: { run_name: string; period_end: string; total_gross: string; total_net: string; employee_count: number }[];
}

const statusLabel: Record<string, string> = {
  draft: "Draft", processing: "Processing", review: "Ready for Review",
  approved: "Approved", locked: "Locked", reopened: "Reopened", paid: "Paid", cancelled: "Cancelled",
};

function fmt(amount: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(parseFloat(amount));
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { day: "numeric", month: "short" });
}

export default function PayrollDashboardPage() {
  const router = useRouter();
  const { data, isLoading } = useQuery({
    queryKey: ["payroll-dashboard"],
    queryFn: async () => (await apiClient.get<DashboardData>("/payroll/dashboard")).data,
  });

  const chartData = (data?.cost_trend ?? []).map((r) => ({
    name: formatDate(r.period_end),
    Gross: parseFloat(r.total_gross),
    Net: parseFloat(r.total_net),
  }));

  return (
    <div className="space-y-6">
      <PageHeader title="Payroll" description="Manage salary processing, payslips, and compensation." />
      <PayrollNav />

      {isLoading || !data ? (
        <p className="text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-4">
            <Card>
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--info-subtle))]">
                  <Users size={16} className="text-[hsl(var(--info))]" />
                </div>
                <div>
                  <p className="text-xl font-semibold font-heading">{data.total_employees_on_payroll}</p>
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">Employees on payroll</p>
                </div>
              </div>
            </Card>
            <Card>
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--warning-subtle))]">
                  <Clock size={16} className="text-[hsl(var(--warning))]" />
                </div>
                <div>
                  <p className="text-xl font-semibold font-heading">{data.pending_approvals}</p>
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">Pending approvals</p>
                </div>
              </div>
            </Card>
            <Card>
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]">
                  <TrendingUp size={16} className="text-[hsl(var(--success))]" />
                </div>
                <div>
                  <p className="text-xl font-semibold font-heading">{data.current_run ? fmt(data.current_run.total_net) : "—"}</p>
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">Latest run net pay</p>
                </div>
              </div>
            </Card>
            <Card>
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--accent))]">
                  <CalendarClock size={16} className="text-[hsl(var(--foreground-muted))]" />
                </div>
                <div>
                  <p className="text-xl font-semibold font-heading">{data.upcoming_pay_date ? formatDate(data.upcoming_pay_date) : "—"}</p>
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">Upcoming pay date</p>
                </div>
              </div>
            </Card>
          </div>

          {data.current_run && (
            <div onClick={() => router.push(`/payroll/${data.current_run!.id}`)} className="cursor-pointer">
              <Card className="transition-colors hover:border-[hsl(var(--border-strong))]">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-heading text-sm font-semibold">{data.current_run.name}</h3>
                      <Badge variant={data.current_run.status === "review" ? "warning" : "success"}>
                        {statusLabel[data.current_run.status] ?? data.current_run.status}
                      </Badge>
                    </div>
                    <p className="text-xs text-[hsl(var(--foreground-muted))]">Current payroll run — click to view details</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono text-sm font-semibold">{fmt(data.current_run.total_gross)} gross</p>
                    <p className="font-mono text-xs text-[hsl(var(--foreground-muted))]">{fmt(data.current_run.total_net)} net</p>
                  </div>
                </div>
              </Card>
            </div>
          )}

          <Card>
            <h3 className="mb-4 text-sm font-semibold">Payroll Cost Trend</h3>
            {chartData.length === 0 ? (
              <p className="text-sm text-[hsl(var(--foreground-muted))]">No payroll runs yet.</p>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                  <Tooltip formatter={(v: number) => `$${v.toLocaleString()}`} />
                  <Bar dataKey="Gross" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="Net" fill="hsl(var(--success))" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
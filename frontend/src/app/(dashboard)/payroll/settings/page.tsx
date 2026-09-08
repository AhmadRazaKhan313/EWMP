"use client";

import { useEffect, useState } from "react";
import { Loader2, Save } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button, Card, PageHeader } from "@/components/atoms";
import { PayrollNav } from "../PayrollNav";

interface Settings {
  frequency: string;
  period_start_day: number;
  pay_date_offset_days: number;
  working_days_method: string;
  fixed_monthly_divisor: string | null;
  rounding_mode: string;
  decimal_precision: number;
  default_currency: string;
  allow_negative_net_salary: boolean;
  minimum_net_salary: string | null;
  maximum_deduction_percentage: string | null;
  proration_method: string;
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-xs font-medium text-[hsl(var(--foreground-subtle))] mb-1">{children}</label>;
}

function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1"
    />
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1"
    />
  );
}

export default function PayrollSettingsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["payroll-settings"],
    queryFn: async () => (await apiClient.get<Settings>("/payroll/settings")).data,
  });

  const [form, setForm] = useState<Settings | null>(null);
  useEffect(() => { if (data) setForm(data); }, [data]);

  const save = useMutation({
    mutationFn: () => apiClient.put("/payroll/settings", form),
    onSuccess: () => {
      toast.success("Payroll settings saved");
      void qc.invalidateQueries({ queryKey: ["payroll-settings"] });
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not save settings";
      toast.error(msg);
    },
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Payroll" description="Manage salary processing, payslips, and compensation." />
      <PayrollNav />

      {isLoading || !form ? (
        <p className="text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>
      ) : (
        <Card className="max-w-2xl">
          <div className="space-y-5">
            <div>
              <h3 className="text-sm font-semibold">Frequency & Period</h3>
              <div className="mt-2 grid grid-cols-2 gap-3">
                <div>
                  <Label>Payroll frequency</Label>
                  <Select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })}>
                    <option value="monthly">Monthly</option>
                    <option value="semi_monthly">Semi-monthly</option>
                    <option value="biweekly">Biweekly</option>
                    <option value="weekly">Weekly</option>
                  </Select>
                </div>
                <div>
                  <Label>Pay date offset (days after period end)</Label>
                  <Input type="number" min={0} value={form.pay_date_offset_days} onChange={(e) => setForm({ ...form, pay_date_offset_days: Number(e.target.value) })} />
                </div>
              </div>
            </div>

            <div className="border-t border-[hsl(var(--border))] pt-4">
              <h3 className="text-sm font-semibold">Working Days & Proration</h3>
              <div className="mt-2 grid grid-cols-2 gap-3">
                <div>
                  <Label>Working-days method</Label>
                  <Select value={form.working_days_method} onChange={(e) => setForm({ ...form, working_days_method: e.target.value })}>
                    <option value="working_days">Working days (Mon–Fri)</option>
                    <option value="calendar_days">Calendar days</option>
                    <option value="fixed_divisor">Fixed divisor</option>
                    <option value="hourly">Hourly</option>
                  </Select>
                </div>
                <div>
                  <Label>Proration method (joining/leaving mid-period)</Label>
                  <Select value={form.proration_method} onChange={(e) => setForm({ ...form, proration_method: e.target.value })}>
                    <option value="calendar_days">Calendar days</option>
                    <option value="working_days">Working days</option>
                    <option value="fixed_divisor">Fixed divisor</option>
                    <option value="hourly">Hourly</option>
                  </Select>
                </div>
                {form.working_days_method === "fixed_divisor" && (
                  <div>
                    <Label>Fixed monthly divisor</Label>
                    <Input type="number" value={form.fixed_monthly_divisor ?? ""} onChange={(e) => setForm({ ...form, fixed_monthly_divisor: e.target.value })} placeholder="e.g. 30" />
                  </div>
                )}
              </div>
            </div>

            <div className="border-t border-[hsl(var(--border))] pt-4">
              <h3 className="text-sm font-semibold">Rounding & Currency</h3>
              <div className="mt-2 grid grid-cols-2 gap-3">
                <div>
                  <Label>Rounding mode</Label>
                  <Select value={form.rounding_mode} onChange={(e) => setForm({ ...form, rounding_mode: e.target.value })}>
                    <option value="half_up">Round half up</option>
                    <option value="half_down">Round half down</option>
                    <option value="bankers">Banker's rounding</option>
                    <option value="floor">Floor</option>
                    <option value="ceiling">Ceiling</option>
                    <option value="none">No rounding</option>
                  </Select>
                </div>
                <div>
                  <Label>Default currency</Label>
                  <Input value={form.default_currency} maxLength={3} onChange={(e) => setForm({ ...form, default_currency: e.target.value.toUpperCase() })} />
                </div>
              </div>
            </div>

            <div className="border-t border-[hsl(var(--border))] pt-4">
              <h3 className="text-sm font-semibold">Validation Guardrails</h3>
              <div className="mt-2 grid grid-cols-2 gap-3">
                <div>
                  <Label>Minimum net salary (blocks finalization below this)</Label>
                  <Input type="number" value={form.minimum_net_salary ?? ""} onChange={(e) => setForm({ ...form, minimum_net_salary: e.target.value })} placeholder="Optional" />
                </div>
                <div>
                  <Label>Maximum deduction % of gross</Label>
                  <Input type="number" max={100} value={form.maximum_deduction_percentage ?? ""} onChange={(e) => setForm({ ...form, maximum_deduction_percentage: e.target.value })} placeholder="Optional" />
                </div>
              </div>
              <label className="mt-3 flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.allow_negative_net_salary} onChange={(e) => setForm({ ...form, allow_negative_net_salary: e.target.checked })} />
                Allow negative net salary (not recommended)
              </label>
            </div>

            <div className="flex justify-end border-t border-[hsl(var(--border))] pt-4">
              <Button onClick={() => save.mutate()} disabled={save.isPending} icon={save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}>
                Save Settings
              </Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

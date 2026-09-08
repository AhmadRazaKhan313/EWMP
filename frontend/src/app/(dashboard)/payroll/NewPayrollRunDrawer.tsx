"use client";

import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button } from "@/components/atoms";

function Label({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="block text-xs font-medium text-[hsl(var(--foreground-subtle))] mb-1">
      {children} {required && <span className="text-[hsl(var(--destructive))]">*</span>}
    </label>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1 hover:border-[hsl(var(--border-strong))]"
    />
  );
}

// Defaults a period to "this calendar month" — the common case — while
// still letting the user pick any custom range for weekly/biweekly runs.
function defaultPeriod() {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { start: iso(start), end: iso(end), pay: iso(end) };
}

export function NewPayrollRunDrawer({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const period = defaultPeriod();
  const [name, setName] = useState(`Payroll — ${new Date().toLocaleString("en-US", { month: "long", year: "numeric" })}`);
  const [periodStart, setPeriodStart] = useState(period.start);
  const [periodEnd, setPeriodEnd] = useState(period.end);
  const [payDate, setPayDate] = useState(period.pay);
  const [currency, setCurrency] = useState("USD");

  const create = useMutation({
    mutationFn: () =>
      apiClient.post("/payroll/runs", {
        name, period_start: periodStart, period_end: periodEnd, pay_date: payDate, currency,
      }),
    onSuccess: (res) => {
      toast.success("Payroll run created — generate payslips when ready");
      void qc.invalidateQueries({ queryKey: ["payroll-runs"] });
      onClose();
      router.push(`/payroll/${res.data.id}`);
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not create payroll run";
      toast.error(msg);
    },
  });

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col bg-[hsl(var(--background))] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div>
            <h2 className="font-heading text-lg font-semibold">New Payroll Run</h2>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">Starts as a draft — nothing is calculated yet</p>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
          <div>
            <Label required>Run name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label required>Period start</Label>
              <Input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} />
            </div>
            <div>
              <Label required>Period end</Label>
              <Input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label required>Pay date</Label>
              <Input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} />
            </div>
            <div>
              <Label>Currency</Label>
              <Input value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[hsl(var(--border))] px-6 py-4">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            onClick={() => create.mutate()}
            disabled={create.isPending || !name || !periodStart || !periodEnd || !payDate}
          >
            {create.isPending && <Loader2 size={14} className="animate-spin" />}
            Create Run
          </Button>
        </div>
      </div>
    </>
  );
}

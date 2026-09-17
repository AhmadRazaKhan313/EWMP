"use client";

import { useState } from "react";
import { X, Download, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Badge, Button } from "@/components/atoms";

interface PaymentItem {
  id: string;
  employee_id: string;
  amount: string;
  bank_name: string | null;
  bank_account_number: string | null;
  status: "pending" | "paid" | "failed";
  payment_reference: string | null;
}

interface PaymentBatch {
  id: string;
  payroll_run_id: string;
  status: string;
  total_amount: string;
  items: PaymentItem[];
}

function fmt(amount: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(parseFloat(amount));
}

const statusVariant: Record<string, "default" | "success" | "error"> = { pending: "default", paid: "success", failed: "error" };

export function PaymentBatchDrawer({ runId, onClose }: { runId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [batchId, setBatchId] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => apiClient.post(`/payroll/runs/${runId}/payment-batch`),
    onSuccess: (res) => {
      toast.success(`Payment batch prepared — ${res.data.item_count} employee(s)`);
      setBatchId(res.data.id);
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not prepare payment batch";
      toast.error(msg);
    },
  });

  const { data: batch, isLoading } = useQuery({
    queryKey: ["payment-batch", batchId],
    queryFn: async () => (await apiClient.get<PaymentBatch>(`/payroll/payment-batches/${batchId}`)).data,
    enabled: !!batchId,
  });

  const markPaid = useMutation({
    mutationFn: (itemId: string) => apiClient.post(`/payroll/payment-batches/${batchId}/items/${itemId}/mark-paid`, {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["payment-batch", batchId] }),
    onError: () => toast.error("Could not mark as paid"),
  });

  const markFailed = useMutation({
    mutationFn: (itemId: string) => apiClient.post(`/payroll/payment-batches/${batchId}/items/${itemId}/mark-failed`, { failure_reason: "Marked failed manually" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["payment-batch", batchId] }),
    onError: () => toast.error("Could not mark as failed"),
  });

  function downloadCsv() {
    if (!batchId) return;
    window.open(`${apiClient.defaults.baseURL}/payroll/payment-batches/${batchId}/csv`, "_blank");
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-lg flex-col bg-[hsl(var(--background))] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <h2 className="font-heading text-lg font-semibold">Payment Batch</h2>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {!batchId ? (
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <p className="text-sm text-[hsl(var(--foreground-muted))]">
                Prepare a bank-transfer batch for this run. Each employee&apos;s current bank details are snapshotted at this moment.
              </p>
              <Button onClick={() => create.mutate()} disabled={create.isPending}>
                {create.isPending && <Loader2 size={14} className="animate-spin" />}
                Prepare Payment Batch
              </Button>
            </div>
          ) : isLoading || !batch ? (
            <p className="text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>
          ) : (
            <>
              <div className="mb-4 flex items-center justify-between">
                <p className="text-sm font-semibold">Total: {fmt(batch.total_amount)}</p>
                <Button size="sm" variant="outline" icon={<Download size={12} />} onClick={downloadCsv}>
                  Download Bank File (CSV)
                </Button>
              </div>

              <div className="divide-y divide-[hsl(var(--border))]">
                {batch.items.map((item) => (
                  <div key={item.id} className="flex items-center justify-between py-2.5">
                    <div>
                      <p className="text-sm">{item.bank_name ?? "No bank on file"} {item.bank_account_number && `· ${item.bank_account_number}`}</p>
                      <p className="font-mono text-xs text-[hsl(var(--foreground-muted))]">{fmt(item.amount)}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={statusVariant[item.status]}>{item.status}</Badge>
                      {item.status === "pending" && (
                        <>
                          <button onClick={() => markPaid.mutate(item.id)} title="Mark paid" className="text-[hsl(var(--success))] hover:opacity-70">
                            <CheckCircle2 size={16} />
                          </button>
                          <button onClick={() => markFailed.mutate(item.id)} title="Mark failed" className="text-[hsl(var(--destructive))] hover:opacity-70">
                            <XCircle size={16} />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

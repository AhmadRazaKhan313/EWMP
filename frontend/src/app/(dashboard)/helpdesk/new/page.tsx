"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button } from "@/components/atoms";

const inp =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]";

/** Raise a ticket as a page (dashboard quick action → /helpdesk/new). */
export default function NewTicketPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [form, setForm] = useState({ title: "", description: "", priority: "medium", category: "Hardware" });
  const create = useMutation({
    mutationFn: () => apiClient.post("/helpdesk/tickets", form),
    onSuccess: () => {
      toast.success("Ticket created");
      void qc.invalidateQueries({ queryKey: ["tickets"] });
      router.push("/helpdesk");
    },
    onError: () => toast.error("Failed to create ticket"),
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="space-y-4">
      <Link href="/helpdesk" className="inline-flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"><ArrowLeft size={14} /> Helpdesk</Link>
      <div className="w-full max-w-2xl space-y-4 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-6 shadow-[var(--shadow-xs)]">
        <h2 className="font-heading text-lg font-semibold">New Support Ticket</h2>
        <div>
          <label className="mb-1 block text-xs font-medium">Title *</label>
          <input value={form.title} onChange={set("title")} placeholder="Brief description of the issue" className={inp} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1 block text-xs font-medium">Category</label>
            <select value={form.category} onChange={set("category")} className={inp}>
              {["Hardware", "Software", "Network", "Access", "Email", "Other"].map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium">Priority</label>
            <select value={form.priority} onChange={set("priority")} className={inp}>
              <option value="low">Low</option><option value="medium">Medium</option>
              <option value="high">High</option><option value="critical">Critical</option>
            </select>
          </div>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium">Description</label>
          <textarea value={form.description} onChange={set("description")} rows={4} placeholder="Detailed description of the issue..." className={inp + " resize-none"} />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => router.push("/helpdesk")}>Cancel</Button>
          <Button disabled={!form.title.trim() || create.isPending} onClick={() => create.mutate()}>
            {create.isPending && <Loader2 size={14} className="animate-spin" />} Submit Ticket
          </Button>
        </div>
      </div>
    </div>
  );
}

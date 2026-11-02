"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button } from "@/components/atoms";
import { useEmployees } from "@/services/employee.service";
import { useAssignAsset } from "@/services/assets.service";

const inp =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]";

interface AssetOption { id: string; name: string; asset_tag: string; category: string | null }

/** Assign an available asset to an employee, as a page (dashboard quick action → /assets/assign). */
export default function AssignAssetPage() {
  const router = useRouter();
  const [assetId, setAssetId] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [notes, setNotes] = useState("");

  const { data: assets, isLoading } = useQuery({
    queryKey: ["assets", "available"],
    queryFn: async () =>
      (await apiClient.get<{ items: AssetOption[] }>("/assets", { params: { status: "available", page_size: 200 } })).data.items,
  });
  const { data: employees } = useEmployees({ page_size: 100 });
  const assign = useAssignAsset();

  function submit() {
    assign.mutate(
      { assetId, employeeId, notes },
      {
        onSuccess: () => { toast.success("Asset assigned"); router.push("/assets"); },
        onError: () => toast.error("Could not assign the asset"),
      },
    );
  }

  return (
    <div className="space-y-4">
      <Link href="/assets" className="inline-flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"><ArrowLeft size={14} /> Assets</Link>
      <div className="w-full max-w-2xl space-y-4 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-6 shadow-[var(--shadow-xs)]">
        <div>
          <h2 className="font-heading text-lg font-semibold">Assign Asset</h2>
          <p className="text-xs text-[hsl(var(--foreground-muted))]">Allocate available equipment to an employee</p>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium">Asset *</label>
          <select value={assetId} onChange={(e) => setAssetId(e.target.value)} className={inp} disabled={isLoading}>
            <option value="">{isLoading ? "Loading…" : assets?.length ? "Select an available asset" : "No available assets"}</option>
            {assets?.map((a) => <option key={a.id} value={a.id}>{a.asset_tag} — {a.name}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium">Employee *</label>
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} className={inp}>
            <option value="">Select an employee</option>
            {employees?.items.map((e) => (
              <option key={e.id} value={e.id}>{e.employee_code} — {e.first_name} {e.last_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium">Notes</label>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className={inp + " resize-none"} />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => router.push("/assets")}>Cancel</Button>
          <Button disabled={!assetId || !employeeId || assign.isPending} onClick={submit}>
            {assign.isPending && <Loader2 size={14} className="animate-spin" />} Assign
          </Button>
        </div>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { X, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button, Badge } from "@/components/atoms";
import { useEmployees } from "@/services/employee.service";
import { useUpdateAsset, useDeleteAsset, useAssignAsset, useReturnAsset } from "@/services/assets.service";

const STATUS_OPTIONS = [
  { value: "available", label: "Available" },
  { value: "assigned", label: "Assigned" },
  { value: "under_repair", label: "Under Repair" },
  { value: "disposed", label: "Disposed" },
  { value: "lost", label: "Lost" },
];

const statusVariant: Record<string, "success" | "warning" | "error" | "default" | "info"> = {
  available: "success",
  assigned: "info",
  under_repair: "warning",
  disposed: "error",
  lost: "error",
};

interface AssetRow {
  id: string;
  name: string;
  asset_tag: string;
  brand: string | null;
  model: string | null;
  status: string;
  location: string | null;
  warranty_expiry: string | null;
  assigned_employee_id: string | null;
}

const inp =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";

export function AssetDrawer({ asset, onClose }: { asset: AssetRow; onClose: () => void }) {
  const { data: employeesData } = useEmployees({ page_size: 100 });
  const updateAsset = useUpdateAsset();
  const deleteAsset = useDeleteAsset();
  const assignAsset = useAssignAsset();
  const returnAsset = useReturnAsset();

  const [name, setName] = useState(asset.name);
  const [brand, setBrand] = useState(asset.brand ?? "");
  const [model, setModel] = useState(asset.model ?? "");
  const [location, setLocation] = useState(asset.location ?? "");
  const [status, setStatus] = useState(asset.status);
  const [warrantyExpiry, setWarrantyExpiry] = useState(asset.warranty_expiry ?? "");
  const [showAssign, setShowAssign] = useState(false);

  const assignedEmployee = employeesData?.items.find((e) => e.id === asset.assigned_employee_id);

  function handleSave() {
    updateAsset.mutate(
      {
        assetId: asset.id,
        body: {
          name: name.trim(),
          brand: brand.trim(),
          model: model.trim(),
          location: location.trim(),
          status,
          warranty_expiry: warrantyExpiry || undefined,
        },
      },
      {
        onSuccess: () => toast.success("Asset updated"),
        onError: () => toast.error("Couldn't update asset"),
      },
    );
  }

  function handleDelete() {
    if (!window.confirm(`Delete "${asset.name}" (${asset.asset_tag})? This can't be undone.`)) return;
    deleteAsset.mutate(asset.id, {
      onSuccess: () => {
        toast.success("Asset deleted");
        onClose();
      },
      onError: () => toast.error("Couldn't delete asset"),
    });
  }

  function handleReturn() {
    if (!window.confirm(`Mark "${asset.name}" as returned by ${assignedEmployee?.full_name ?? "this employee"}?`)) return;
    returnAsset.mutate(
      { assetId: asset.id },
      {
        onSuccess: () => toast.success("Asset returned"),
        onError: () => toast.error("Couldn't return asset"),
      },
    );
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div>
            <h2 className="font-heading text-sm font-semibold">{asset.name}</h2>
            <p className="font-mono text-[11px] text-[hsl(var(--foreground-muted))]">{asset.asset_tag}</p>
          </div>
          <button onClick={onClose} className="text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* Edit fields */}
          <div className="space-y-3">
            <h3 className="text-xs font-semibold text-[hsl(var(--foreground-muted))]">DETAILS</h3>
            <div>
              <label className="mb-1 block text-xs font-medium">Name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} className={inp} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium">Brand</label>
                <input value={brand} onChange={(e) => setBrand(e.target.value)} className={inp} />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium">Model</label>
                <input value={model} onChange={(e) => setModel(e.target.value)} className={inp} />
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium">Location</label>
              <input value={location} onChange={(e) => setLocation(e.target.value)} className={inp} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium">Status</label>
                <select value={status} onChange={(e) => setStatus(e.target.value)} className={inp}>
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium">Warranty Expiry</label>
                <input type="date" value={warrantyExpiry} onChange={(e) => setWarrantyExpiry(e.target.value)} className={inp} />
              </div>
            </div>
            <div className="flex justify-end">
              <Button size="sm" onClick={handleSave} disabled={updateAsset.isPending}>
                {updateAsset.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save Changes"}
              </Button>
            </div>
          </div>

          {/* Assignment */}
          <div className="space-y-2 border-t border-[hsl(var(--border))] pt-5">
            <h3 className="text-xs font-semibold text-[hsl(var(--foreground-muted))]">ASSIGNMENT</h3>
            {asset.assigned_employee_id ? (
              <div className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] p-3">
                <div>
                  <p className="text-sm font-medium">{assignedEmployee?.full_name ?? "Assigned employee"}</p>
                  {assignedEmployee?.employee_code && (
                    <p className="text-xs text-[hsl(var(--foreground-muted))]">{assignedEmployee.employee_code}</p>
                  )}
                </div>
                <button
                  onClick={handleReturn}
                  disabled={returnAsset.isPending}
                  className="text-xs text-[hsl(var(--destructive))] hover:underline"
                >
                  Mark Returned
                </button>
              </div>
            ) : showAssign ? (
              <select
                className={inp}
                defaultValue=""
                onChange={(e) => {
                  if (!e.target.value) return;
                  assignAsset.mutate(
                    { assetId: asset.id, employeeId: e.target.value },
                    {
                      onSuccess: () => {
                        toast.success("Asset assigned");
                        setShowAssign(false);
                      },
                      onError: () => toast.error("Couldn't assign asset"),
                    },
                  );
                }}
              >
                <option value="" disabled>Select an employee…</option>
                {employeesData?.items.map((emp) => (
                  <option key={emp.id} value={emp.id}>{emp.full_name} ({emp.employee_code})</option>
                ))}
              </select>
            ) : (
              <button
                onClick={() => setShowAssign(true)}
                className="w-full rounded-lg border border-dashed border-[hsl(var(--border))] p-3 text-xs text-[hsl(var(--foreground-muted))] hover:border-[hsl(var(--primary))] hover:text-[hsl(var(--primary))]"
              >
                + Assign to an employee
              </button>
            )}
          </div>

          {/* Danger zone */}
          <div className="border-t border-[hsl(var(--border))] pt-5">
            <button
              onClick={handleDelete}
              disabled={deleteAsset.isPending}
              className="flex w-full items-center justify-center gap-1.5 rounded-md border border-[hsl(var(--destructive))] py-2 text-xs font-medium text-[hsl(var(--destructive))] hover:bg-[hsl(var(--status-error-bg))]"
            >
              <Trash2 size={13} /> Delete Asset
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

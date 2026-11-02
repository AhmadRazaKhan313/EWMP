"use client";

import { useState } from "react";
import { Lock, Trash2, Check, X } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { useAuthStore } from "@/store/auth.store";
import { Badge, Button, Card, CardHeader, EmptyState } from "@/components/atoms";

export interface BreakPolicy {
  id: string; scope: "organization" | "department" | "shift" | "employee"; scope_id: string | null;
  start_time: string; duration_minutes: number; days: number[] | null; is_active: boolean;
}
interface BreakOverride { id: string; employee_id: string | null; department_id: string | null; on_date: string; start_time: string | null; duration_minutes: number | null; reason: string | null }
interface UnlockRequest { id: string; employee_name: string; employee_code: string; break_date: string; reason: string | null; status: string }
type Opt = { id: string; label: string };

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const field = "h-9 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 text-sm";

type Row = Record<string, string>;
const unwrap = (d: unknown): Row[] => (Array.isArray(d) ? d : (d as { items?: Row[] } | null)?.items ?? []);

export function usePendingBreakRequests() {
  const can = useAuthStore((s) => s.hasPermission)("break.approve");
  return useQuery({
    queryKey: ["break-requests", "pending"],
    enabled: can,
    retry: false,
    refetchInterval: 15_000,
    queryFn: async () => (await apiClient.get<{ pending_count: number; items: UnlockRequest[] }>("/break/unlock-requests", { params: { status: "pending" } })).data,
  });
}

export function BreakSettings() {
  const qc = useQueryClient();
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const canManage = hasPermission("break.manage");
  const canApprove = hasPermission("break.approve");

  const { data: policies = [] } = useQuery({ queryKey: ["break-policies"], enabled: canManage,
    queryFn: async () => (await apiClient.get<BreakPolicy[]>("/break/policies")).data });
  const { data: overrides = [] } = useQuery({ queryKey: ["break-overrides"], enabled: canManage,
    queryFn: async () => (await apiClient.get<BreakOverride[]>("/break/overrides")).data });
  const { data: depts = [] } = useQuery({ queryKey: ["break-opt-dept"], enabled: canManage,
    queryFn: async () => unwrap((await apiClient.get("/departments")).data).map((d) => ({ id: d.id, label: d.name })) as Opt[] });
  const { data: shifts = [] } = useQuery({ queryKey: ["break-opt-shift"], enabled: canManage,
    queryFn: async () => unwrap((await apiClient.get("/shifts")).data).map((d) => ({ id: d.id, label: d.name })) as Opt[] });
  const { data: emps = [] } = useQuery({ queryKey: ["break-opt-emp"], enabled: canManage,
    queryFn: async () => unwrap((await apiClient.get("/employees", { params: { page_size: 200 } })).data)
      .map((e) => ({ id: e.id, label: `${e.full_name} (${e.employee_code})` })) as Opt[] });
  const pending = usePendingBreakRequests();

  const label = (kind: string, id: string | null) =>
    (kind === "department" ? depts : kind === "shift" ? shifts : emps).find((o) => o.id === id)?.label ?? "—";

  const org = policies.find((p) => p.scope === "organization");
  const [orgForm, setOrgForm] = useState<{ start: string; dur: number; days: number[]; active: boolean } | null>(null);
  const of = orgForm ?? { start: org?.start_time ?? "13:00", dur: org?.duration_minutes ?? 60, days: org?.days ?? [], active: org?.is_active ?? true };

  const refresh = () => { qc.invalidateQueries({ queryKey: ["break-policies"] }); qc.invalidateQueries({ queryKey: ["break-overrides"] }); };
  const fail = (e: unknown) => toast.error((e as { response?: { data?: { message?: string } } })?.response?.data?.message ?? "Something went wrong");

  const saveOrg = useMutation({
    mutationFn: () => apiClient.put("/break/policy", { start_time: of.start, duration_minutes: of.dur, days: of.days.length ? of.days : null, is_active: of.active }),
    onSuccess: () => { toast.success("Default break saved"); setOrgForm(null); refresh(); }, onError: fail,
  });

  const [np, setNp] = useState({ scope: "department", scope_id: "", start: "13:00", dur: 60 });
  const addPolicy = useMutation({
    mutationFn: () => apiClient.post("/break/policies", { scope: np.scope, scope_id: np.scope_id, start_time: np.start, duration_minutes: np.dur }),
    onSuccess: () => { toast.success("Break rule added"); setNp({ ...np, scope_id: "" }); refresh(); }, onError: fail,
  });
  const delPolicy = useMutation({ mutationFn: (id: string) => apiClient.delete(`/break/policies/${id}`), onSuccess: refresh, onError: fail });

  const [no, setNo] = useState({ target: "employee", id: "", date: "", none: false, start: "14:00", dur: 60, reason: "" });
  const addOverride = useMutation({
    mutationFn: () => apiClient.post("/break/overrides", {
      ...(no.target === "employee" ? { employee_ids: [no.id] } : { department_id: no.id }),
      on_date: no.date, start_time: no.none ? null : no.start, duration_minutes: no.none ? null : no.dur, reason: no.reason || null,
    }),
    onSuccess: () => { toast.success("Day override saved"); setNo({ ...no, id: "", reason: "" }); refresh(); }, onError: fail,
  });
  const delOverride = useMutation({ mutationFn: (id: string) => apiClient.delete(`/break/overrides/${id}`), onSuccess: refresh, onError: fail });

  const decide = useMutation({
    mutationFn: ({ id, ok }: { id: string; ok: boolean }) => apiClient.post(`/break/unlock-requests/${id}/${ok ? "approve" : "deny"}`),
    onSuccess: (_, v) => { toast.success(v.ok ? "Approved — work time resumes" : "Denied — computer stays locked"); qc.invalidateQueries({ queryKey: ["break-requests"] }); },
    onError: fail,
  });

  return (
    <div className="space-y-4">
      {canApprove && (
        <Card>
          <CardHeader title="Unlock requests" description="Employees asking to keep working during the break. Refreshes every 15 seconds." />
          {!pending.data?.items.length ? (
            <EmptyState icon={Lock} title="No pending requests" description="Nobody is waiting for an unlock." />
          ) : (
            <ul className="divide-y divide-[hsl(var(--border))]">
              {pending.data.items.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-3 py-3">
                  <div>
                    <p className="text-sm font-medium">{r.employee_name} <span className="text-[hsl(var(--foreground-muted))]">({r.employee_code})</span></p>
                    <p className="text-xs text-[hsl(var(--foreground-muted))]">{r.reason || "No reason given"}</p>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" icon={<Check size={14} />} onClick={() => decide.mutate({ id: r.id, ok: true })}>Approve</Button>
                    <Button size="sm" variant="outline" icon={<X size={14} />} onClick={() => decide.mutate({ id: r.id, ok: false })}>Deny</Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {canManage && (<>
        <Card>
          <CardHeader title="Default break" description="All laptops lock during this window and stay locked until it ends." />
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs">Starts at<input aria-label="Start time" type="time" className={`${field} mt-1 block`} value={of.start} onChange={(e) => setOrgForm({ ...of, start: e.target.value })} /></label>
            <label className="text-xs">Minutes<input aria-label="Duration" type="number" min={5} max={480} className={`${field} mt-1 block w-24`} value={of.dur} onChange={(e) => setOrgForm({ ...of, dur: Number(e.target.value) })} /></label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={of.active} onChange={(e) => setOrgForm({ ...of, active: e.target.checked })} />Active</label>
            <Button onClick={() => saveOrg.mutate()} disabled={saveOrg.isPending}>Save default</Button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="text-[hsl(var(--foreground-muted))]">Days (none ticked = every day):</span>
            {DAYS.map((d, i) => (
              <label key={d} className="flex items-center gap-1">
                <input type="checkbox" checked={of.days.includes(i)} onChange={(e) => setOrgForm({ ...of, days: e.target.checked ? [...of.days, i] : of.days.filter((x) => x !== i) })} />{d}
              </label>
            ))}
          </div>
        </Card>

        <Card>
          <CardHeader title="Different break for a group" description="Department, shift or a single employee. The most specific rule wins." />
          <div className="flex flex-wrap items-end gap-3">
            <select aria-label="Scope" className={field} value={np.scope} onChange={(e) => setNp({ ...np, scope: e.target.value, scope_id: "" })}>
              <option value="department">Department</option><option value="shift">Shift</option><option value="employee">Employee</option>
            </select>
            <select aria-label="Target" className={field} value={np.scope_id} onChange={(e) => setNp({ ...np, scope_id: e.target.value })}>
              <option value="">Select…</option>
              {(np.scope === "department" ? depts : np.scope === "shift" ? shifts : emps).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
            <input aria-label="Group start time" type="time" className={field} value={np.start} onChange={(e) => setNp({ ...np, start: e.target.value })} />
            <input aria-label="Group duration" type="number" min={5} className={`${field} w-24`} value={np.dur} onChange={(e) => setNp({ ...np, dur: Number(e.target.value) })} />
            <Button disabled={!np.scope_id || addPolicy.isPending} onClick={() => addPolicy.mutate()}>Add</Button>
          </div>
          <ul className="mt-3 divide-y divide-[hsl(var(--border))]">
            {policies.filter((p) => p.scope !== "organization").map((p) => (
              <li key={p.id} className="flex items-center justify-between py-2 text-sm">
                <span><Badge variant="brand">{p.scope}</Badge> <span className="ml-2">{label(p.scope, p.scope_id)}</span> — {p.start_time} for {p.duration_minutes} min</span>
                <button aria-label="Delete rule" className="text-[hsl(var(--destructive))]" onClick={() => delPolicy.mutate(p.id)}><Trash2 size={15} /></button>
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <CardHeader title="One-day change" description="Move the break on a specific date, or skip it for someone." />
          <div className="flex flex-wrap items-end gap-3">
            <select aria-label="Override target type" className={field} value={no.target} onChange={(e) => setNo({ ...no, target: e.target.value, id: "" })}>
              <option value="employee">Employee</option><option value="department">Department</option>
            </select>
            <select aria-label="Override target" className={field} value={no.id} onChange={(e) => setNo({ ...no, id: e.target.value })}>
              <option value="">Select…</option>
              {(no.target === "employee" ? emps : depts).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
            <input aria-label="Override date" type="date" className={field} value={no.date} onChange={(e) => setNo({ ...no, date: e.target.value })} />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={no.none} onChange={(e) => setNo({ ...no, none: e.target.checked })} />No break that day</label>
            {!no.none && (<>
              <input aria-label="Override start time" type="time" className={field} value={no.start} onChange={(e) => setNo({ ...no, start: e.target.value })} />
              <input aria-label="Override duration" type="number" min={5} className={`${field} w-24`} value={no.dur} onChange={(e) => setNo({ ...no, dur: Number(e.target.value) })} />
            </>)}
            <input aria-label="Reason" placeholder="Reason (optional)" className={`${field} w-48`} value={no.reason} onChange={(e) => setNo({ ...no, reason: e.target.value })} />
            <Button disabled={!no.id || !no.date || addOverride.isPending} onClick={() => addOverride.mutate()}>Save change</Button>
          </div>
          <ul className="mt-3 divide-y divide-[hsl(var(--border))]">
            {overrides.map((o) => (
              <li key={o.id} className="flex items-center justify-between py-2 text-sm">
                <span>{o.on_date} — {o.employee_id ? label("employee", o.employee_id) : label("department", o.department_id)} — {o.start_time ? `${o.start_time} for ${o.duration_minutes} min` : "no break"}{o.reason ? ` (${o.reason})` : ""}</span>
                <button aria-label="Delete override" className="text-[hsl(var(--destructive))]" onClick={() => delOverride.mutate(o.id)}><Trash2 size={15} /></button>
              </li>
            ))}
          </ul>
        </Card>
      </>)}
    </div>
  );
}

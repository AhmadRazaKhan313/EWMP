"use client";
import { useState } from "react";
import { Users, Plus, Trash2, X, UserPlus, Crown, Search } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button, EmptyState, PageHeader } from "@/components/atoms";

const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]";

/* ───────────── Members drawer ───────────── */
function MembersPanel({ team, onClose }: { team: any; onClose: () => void }) {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<string[]>([]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["teams"] });
    void qc.invalidateQueries({ queryKey: ["team-members", team.id] });
    void qc.invalidateQueries({ queryKey: ["team-available", team.id] });
  };

  const members = useQuery({
    queryKey: ["team-members", team.id],
    queryFn: async () => (await apiClient.get(`/teams/${team.id}/members`)).data,
  });
  const available = useQuery({
    queryKey: ["team-available", team.id],
    queryFn: async () => (await apiClient.get(`/teams/${team.id}/available-employees`)).data,
  });

  const add = useMutation({
    mutationFn: () => apiClient.post(`/teams/${team.id}/members`, { employee_ids: picked }),
    onSuccess: () => { toast.success("Members added"); setPicked([]); refresh(); },
  });
  const remove = useMutation({
    mutationFn: (eid: string) => apiClient.delete(`/teams/${team.id}/members/${eid}`),
    onSuccess: () => { toast.success("Member removed"); refresh(); },
  });
  const setLead = useMutation({
    mutationFn: (eid: string) => apiClient.patch(`/teams/${team.id}`, { lead_employee_id: eid }),
    onSuccess: () => { toast.success("Team lead updated"); refresh(); },
  });

  const list = (members.data?.items ?? []) as any[];
  const pool = ((available.data?.items ?? []) as any[]).filter((e) =>
    `${e.full_name} ${e.employee_code} ${e.email ?? ""}`.toLowerCase().includes(search.toLowerCase())
  );
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div className="h-full w-full max-w-xl overflow-y-auto bg-[hsl(var(--background))] p-6 space-y-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full text-white font-bold" style={{ backgroundColor: team.color }}>{team.name[0]}</div>
            <div>
              <h2 className="font-heading text-base font-semibold">{team.name}</h2>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">{list.length} member{list.length === 1 ? "" : "s"}</p>
            </div>
          </div>
          <button onClick={onClose} className="rounded p-1 hover:bg-[hsl(var(--secondary))]"><X size={16} /></button>
        </div>

        {/* current members */}
        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[hsl(var(--foreground-muted))]">Current members</h3>
          {members.isLoading ? <div className="h-16 rounded-lg bg-[hsl(var(--secondary))] animate-pulse" />
          : list.length === 0 ? <p className="rounded-lg border border-dashed border-[hsl(var(--border))] p-4 text-center text-sm text-[hsl(var(--foreground-muted))]">No members yet — add some below.</p>
          : list.map((m) => (
            <div key={m.id} className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{m.full_name} {m.is_lead && <span className="ml-1 inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700"><Crown size={10} />Lead</span>}</p>
                <p className="truncate text-xs text-[hsl(var(--foreground-muted))]">{m.employee_code}{m.email ? ` · ${m.email}` : ""}</p>
              </div>
              <div className="flex shrink-0 gap-1">
                {!m.is_lead && <Button variant="outline" size="sm" onClick={() => setLead.mutate(m.id)}>Make lead</Button>}
                <Button variant="outline" size="sm" onClick={() => { if (confirm(`Remove ${m.full_name}?`)) remove.mutate(m.id); }}>Remove</Button>
              </div>
            </div>
          ))}
        </section>

        {/* add members */}
        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[hsl(var(--foreground-muted))]">Add members</h3>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[hsl(var(--foreground-muted))]" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name, code or email" className={inp + " pl-9"} />
          </div>
          <div className="max-h-64 overflow-y-auto rounded-lg border border-[hsl(var(--border))] divide-y divide-[hsl(var(--border))]">
            {available.isLoading ? <p className="p-3 text-sm">Loading…</p>
            : pool.length === 0 ? <p className="p-3 text-sm text-[hsl(var(--foreground-muted))]">No employees available.</p>
            : pool.map((e) => (
              <label key={e.id} className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-[hsl(var(--secondary))]">
                <input type="checkbox" checked={picked.includes(e.id)} onChange={() => toggle(e.id)} />
                <div className="min-w-0">
                  <p className="truncate text-sm">{e.full_name}</p>
                  <p className="truncate text-xs text-[hsl(var(--foreground-muted))]">{e.employee_code}{e.email ? ` · ${e.email}` : ""}</p>
                </div>
              </label>
            ))}
          </div>
          <div className="flex justify-end">
            <Button size="sm" icon={<UserPlus size={14} />} disabled={picked.length === 0 || add.isPending} onClick={() => add.mutate()}>
              {add.isPending ? "Adding..." : `Add ${picked.length || ""} selected`}
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}

/* ───────────── Page ───────────── */
export default function TeamsPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [openTeam, setOpenTeam] = useState<any | null>(null);
  const [form, setForm] = useState({ name: "", description: "", color: "#3b82f6" });

  const { data, isLoading } = useQuery({ queryKey: ["teams"], queryFn: async () => (await apiClient.get("/teams")).data });
  const teams = (data?.items ?? []) as any[];

  const create = useMutation({
    mutationFn: async (b: object) => (await apiClient.post("/teams", b)).data,
    onSuccess: async (res) => {
      toast.success("Team created — now add members");
      await qc.invalidateQueries({ queryKey: ["teams"] });
      setShowForm(false);
      setForm({ name: "", description: "", color: "#3b82f6" });
      setOpenTeam({ id: res.id, name: form.name, color: form.color });   // jump straight to adding members
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete(`/teams/${id}`),
    onSuccess: () => { toast.success("Deleted"); void qc.invalidateQueries({ queryKey: ["teams"] }); },
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Teams" description="Cross-functional teams and groups." action={<Button icon={<Plus size={15} />} onClick={() => setShowForm(true)}>New Team</Button>} />

      {showForm && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 space-y-4">
          <h3 className="font-heading text-sm font-semibold">New Team</h3>
          <div className="grid grid-cols-3 gap-4">
            <div className="col-span-2"><label className="block text-xs font-medium mb-1">Team Name *</label><input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Product Team" className={inp} /></div>
            <div><label className="block text-xs font-medium mb-1">Color</label><input type="color" value={form.color} onChange={(e) => setForm((f) => ({ ...f, color: e.target.value }))} className="h-10 w-full rounded-md border border-[hsl(var(--border))] px-1" /></div>
          </div>
          <div><label className="block text-xs font-medium mb-1">Description</label><textarea value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} rows={2} placeholder="What does this team do?" className={inp + " resize-none"} /></div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
            <Button size="sm" disabled={!form.name || create.isPending} onClick={() => create.mutate(form)}>{create.isPending ? "Saving..." : "Create Team"}</Button>
          </div>
        </div>
      )}

      {isLoading ? <div className="grid grid-cols-3 gap-4">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-24 rounded-xl bg-[hsl(var(--secondary))] animate-pulse" />)}</div>
      : teams.length === 0 ? <EmptyState icon={Users} title="No teams yet" description="Create your first team." action={<Button icon={<Plus size={14} />} onClick={() => setShowForm(true)}>Create Team</Button>} />
      : <div className="grid grid-cols-3 gap-4">{teams.map((t) => (
        <div key={t.id} onClick={() => setOpenTeam(t)} className="group relative cursor-pointer rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 shadow-sm hover:border-[hsl(var(--border-strong))] transition-colors">
          <button onClick={(e) => { e.stopPropagation(); if (confirm("Delete this team?")) remove.mutate(t.id); }} className="absolute right-3 top-3 opacity-0 group-hover:opacity-100 flex h-6 w-6 items-center justify-center rounded hover:bg-[hsl(var(--status-error-bg))] text-[hsl(var(--destructive))]"><Trash2 size={12} /></button>
          <div className="flex items-center gap-3 mb-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-full text-white text-sm font-bold" style={{ backgroundColor: t.color }}>{t.name[0]}</div>
            <div><p className="font-semibold text-sm">{t.name}</p><p className="font-mono text-xs text-[hsl(var(--foreground-muted))]">{t.slug}</p></div>
          </div>
          {t.description && <p className="text-xs text-[hsl(var(--foreground-muted))] mt-1">{t.description}</p>}
          <div className="mt-3 flex items-center justify-between text-xs text-[hsl(var(--foreground-muted))]">
            <span className="inline-flex items-center gap-1"><Users size={12} />{t.member_count} member{t.member_count === 1 ? "" : "s"}</span>
            {t.lead_name && <span className="inline-flex items-center gap-1"><Crown size={12} />{t.lead_name}</span>}
          </div>
        </div>
      ))}</div>}

      {openTeam && <MembersPanel team={openTeam} onClose={() => setOpenTeam(null)} />}
    </div>
  );
}
"use client";
import { useState } from "react";
import { Users, Plus, Trash2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button, Card, EmptyState, PageHeader } from "@/components/atoms";

export default function TeamsPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name:"", description:"", color:"#3b82f6" });
  const { data, isLoading } = useQuery({ queryKey:["teams"], queryFn: async () => { const {data} = await apiClient.get("/teams"); return data; }});
  const create = useMutation({ mutationFn: (b:object) => apiClient.post("/teams", b), onSuccess: () => { toast.success("Team created"); void qc.invalidateQueries({queryKey:["teams"]}); setShowForm(false); }});
  const remove = useMutation({ mutationFn: (id:string) => apiClient.delete(`/teams/${id}`), onSuccess: () => { toast.success("Deleted"); void qc.invalidateQueries({queryKey:["teams"]}); }});
  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";
  const teams = data?.items ?? [];
  return (
    <div className="space-y-6">
      <PageHeader title="Teams" description="Cross-functional teams and groups." action={<Button icon={<Plus size={15}/>} onClick={()=>setShowForm(true)}>New Team</Button>}/>
      {showForm && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 space-y-4">
          <h3 className="font-heading text-sm font-semibold">New Team</h3>
          <div className="grid grid-cols-3 gap-4">
            <div className="col-span-2"><label className="block text-xs font-medium mb-1">Team Name *</label><input value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} placeholder="Product Team" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Color</label><input type="color" value={form.color} onChange={e=>setForm(f=>({...f,color:e.target.value}))} className="h-9 w-full rounded-md border border-[hsl(var(--border))] px-1"/></div>
          </div>
          <div><label className="block text-xs font-medium mb-1">Description</label><textarea value={form.description} onChange={e=>setForm(f=>({...f,description:e.target.value}))} rows={2} placeholder="What does this team do?" className={inp+" resize-none"}/></div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={()=>setShowForm(false)}>Cancel</Button>
            <Button size="sm" disabled={!form.name||create.isPending} onClick={()=>create.mutate(form)}>{create.isPending?"Saving...":"Create Team"}</Button>
          </div>
        </div>
      )}
      {isLoading ? <div className="grid grid-cols-3 gap-4">{Array.from({length:6}).map((_,i)=><div key={i} className="h-24 rounded-xl bg-[hsl(var(--secondary))] animate-pulse"/>)}</div>
      : teams.length===0 ? <EmptyState icon={Users} title="No teams yet" description="Create your first team." action={<Button icon={<Plus size={14}/>} onClick={()=>setShowForm(true)}>Create Team</Button>}/>
      : <div className="grid grid-cols-3 gap-4">{teams.map((t:any)=>(
        <div key={t.id} className="group relative rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 shadow-sm hover:border-[hsl(var(--border-strong))] transition-colors">
          <button onClick={()=>{if(confirm("Delete?"))remove.mutate(t.id);}} className="absolute right-3 top-3 opacity-0 group-hover:opacity-100 flex h-6 w-6 items-center justify-center rounded hover:bg-[hsl(var(--status-error-bg))] text-[hsl(var(--destructive))]"><Trash2 size={12}/></button>
          <div className="flex items-center gap-3 mb-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-full text-white text-sm font-bold" style={{backgroundColor:t.color}}>{t.name[0]}</div>
            <div><p className="font-semibold text-sm">{t.name}</p><p className="font-mono text-xs text-[hsl(var(--foreground-muted))]">{t.slug}</p></div>
          </div>
          {t.description&&<p className="text-xs text-[hsl(var(--foreground-muted))] mt-1">{t.description}</p>}
        </div>
      ))}</div>}
    </div>
  );
}
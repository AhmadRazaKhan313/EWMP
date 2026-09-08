"use client";
import { useState } from "react";
import { Building2, Plus, MapPin, Phone, Edit, Trash2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button, Card, EmptyState, PageHeader } from "@/components/atoms";

export default function BranchesPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name:"", code:"", city:"", country:"", phone:"", timezone:"UTC", is_headquarters:false });
  const { data, isLoading } = useQuery({ queryKey:["branches"], queryFn: async () => { const {data} = await apiClient.get("/branches"); return data; }});
  const create = useMutation({ mutationFn: (b:object) => apiClient.post("/branches", b), onSuccess: () => { toast.success("Branch created"); void qc.invalidateQueries({queryKey:["branches"]}); setShowForm(false); setForm({name:"",code:"",city:"",country:"",phone:"",timezone:"UTC",is_headquarters:false}); }});
  const remove = useMutation({ mutationFn: (id:string) => apiClient.delete(`/branches/${id}`), onSuccess: () => { toast.success("Deleted"); void qc.invalidateQueries({queryKey:["branches"]}); }});
  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";
  const branches = data?.items ?? [];
  return (
    <div className="space-y-6">
      <PageHeader title="Branches" description="Manage office locations and branches." action={<Button icon={<Plus size={15}/>} onClick={()=>setShowForm(true)}>New Branch</Button>}/>
      {showForm && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 space-y-4">
          <h3 className="font-heading text-sm font-semibold">New Branch</h3>
          <div className="grid grid-cols-3 gap-4">
            <div><label className="block text-xs font-medium mb-1">Name *</label><input value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} placeholder="Karachi Office" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Code</label><input value={form.code} onChange={e=>setForm(f=>({...f,code:e.target.value.toUpperCase()}))} placeholder="KHI" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">City</label><input value={form.city} onChange={e=>setForm(f=>({...f,city:e.target.value}))} placeholder="Karachi" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Country</label><input value={form.country} onChange={e=>setForm(f=>({...f,country:e.target.value}))} placeholder="Pakistan" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Phone</label><input value={form.phone} onChange={e=>setForm(f=>({...f,phone:e.target.value}))} placeholder="+92 21..." className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Timezone</label><select value={form.timezone} onChange={e=>setForm(f=>({...f,timezone:e.target.value}))} className={inp}><option value="UTC">UTC</option><option value="Asia/Karachi">Asia/Karachi</option><option value="America/New_York">America/New_York</option><option value="Europe/London">Europe/London</option></select></div>
          </div>
          <div className="flex items-center gap-2"><input type="checkbox" id="hq" checked={form.is_headquarters} onChange={e=>setForm(f=>({...f,is_headquarters:e.target.checked}))}/><label htmlFor="hq" className="text-sm">Headquarters</label></div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={()=>setShowForm(false)}>Cancel</Button>
            <Button size="sm" disabled={!form.name||create.isPending} onClick={()=>create.mutate(form)}>{create.isPending?"Saving...":"Create Branch"}</Button>
          </div>
        </div>
      )}
      <div className="grid grid-cols-3 gap-4">
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]"><Building2 size={16}/></div><div><p className="text-2xl font-semibold font-heading">{branches.length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Total Branches</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]"><Building2 size={16} className="text-[hsl(var(--success))]"/></div><div><p className="text-2xl font-semibold font-heading">{branches.filter((b:any)=>b.is_headquarters).length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">HQ</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--info-subtle))]"><Building2 size={16} className="text-[hsl(var(--info))]"/></div><div><p className="text-2xl font-semibold font-heading">{branches.filter((b:any)=>b.is_active).length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Active</p></div></div></Card>
      </div>
      {isLoading ? <div className="space-y-2">{Array.from({length:3}).map((_,i)=><div key={i} className="h-20 rounded-xl bg-[hsl(var(--secondary))] animate-pulse"/>)}</div>
      : branches.length===0 ? <EmptyState icon={Building2} title="No branches yet" description="Add your first branch location." action={<Button icon={<Plus size={14}/>} onClick={()=>setShowForm(true)}>Add Branch</Button>}/>
      : <div className="grid grid-cols-2 gap-4">{branches.map((b:any)=>(
        <div key={b.id} className="group rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 shadow-sm hover:border-[hsl(var(--border-strong))] transition-colors">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]"><Building2 size={18}/></div>
              <div><div className="flex items-center gap-2"><p className="font-semibold text-sm">{b.name}</p>{b.is_headquarters&&<span className="text-[10px] bg-[hsl(var(--warning-subtle))] text-[hsl(var(--warning))] px-1.5 py-0.5 rounded-full font-medium">HQ</span>}</div>{b.code&&<span className="font-mono text-xs text-[hsl(var(--foreground-muted))]">{b.code}</span>}</div>
            </div>
            <button onClick={()=>{if(confirm("Delete?"))remove.mutate(b.id);}} className="opacity-0 group-hover:opacity-100 flex h-7 w-7 items-center justify-center rounded-md hover:bg-[hsl(var(--status-error-bg))] text-[hsl(var(--destructive))]"><Trash2 size={13}/></button>
          </div>
          <div className="mt-3 space-y-1.5">
            {(b.city||b.country)&&<div className="flex items-center gap-2 text-xs text-[hsl(var(--foreground-muted))]"><MapPin size={12}/><span>{[b.city,b.country].filter(Boolean).join(", ")}</span></div>}
            {b.phone&&<div className="flex items-center gap-2 text-xs text-[hsl(var(--foreground-muted))]"><Phone size={12}/><span>{b.phone}</span></div>}
          </div>
        </div>
      ))}</div>}
    </div>
  );
}
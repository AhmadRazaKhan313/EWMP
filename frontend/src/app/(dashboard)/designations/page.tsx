"use client";
import { useState } from "react";
import { Briefcase, Plus, Edit, Trash2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";

const LEVELS = [
  { value:1, label:"Level 1 — Individual Contributor" },
  { value:2, label:"Level 2 — Senior / Lead" },
  { value:3, label:"Level 3 — Manager" },
  { value:4, label:"Level 4 — Director" },
  { value:5, label:"Level 5 — VP / Head" },
  { value:6, label:"Level 6 — C-Suite / Executive" },
];

export default function DesignationsPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string|null>(null);
  const [form, setForm] = useState({ name:"", code:"", level:1, description:"" });

  const { data, isLoading } = useQuery({ queryKey:["designations"], queryFn: async () => { const {data} = await apiClient.get("/designations"); return data; }});
  const create = useMutation({ mutationFn: (b:object) => apiClient.post("/designations", b), onSuccess: () => { toast.success("Designation created"); void qc.invalidateQueries({queryKey:["designations"]}); setShowForm(false); setForm({name:"",code:"",level:1,description:""}); }});
  const update = useMutation({ mutationFn: ({id,b}:{id:string;b:object}) => apiClient.patch(`/designations/${id}`, b), onSuccess: () => { toast.success("Updated"); void qc.invalidateQueries({queryKey:["designations"]}); setEditId(null); }});
  const remove = useMutation({ mutationFn: (id:string) => apiClient.delete(`/designations/${id}`), onSuccess: () => { toast.success("Deleted"); void qc.invalidateQueries({queryKey:["designations"]}); }});

  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";
  const designations = data?.items ?? [];

  const grouped = LEVELS.map(l => ({ ...l, items: designations.filter((d:any) => d.level === l.value) })).filter(g => g.items.length > 0);

  const FormPanel = ({ defaultVals, onSave, onCancel, saving }: { defaultVals?: any; onSave:(b:object)=>void; onCancel:()=>void; saving:boolean }) => {
    const [f, setF] = useState(defaultVals ?? { name:"", code:"", level:1, description:"" });
    return (
      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 space-y-4">
        <h3 className="font-heading text-sm font-semibold">{defaultVals ? "Edit Designation" : "New Designation"}</h3>
        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2"><label className="block text-xs font-medium mb-1">Title *</label><input value={f.name} onChange={e=>setF((x:any)=>({...x,name:e.target.value}))} placeholder="Senior Software Engineer" className={inp}/></div>
          <div><label className="block text-xs font-medium mb-1">Code</label><input value={f.code} onChange={e=>setF((x:any)=>({...x,code:e.target.value.toUpperCase()}))} placeholder="SSE" className={inp}/></div>
        </div>
        <div><label className="block text-xs font-medium mb-1">Level</label><select value={f.level} onChange={e=>setF((x:any)=>({...x,level:parseInt(e.target.value)}))} className={inp}>{LEVELS.map(l=><option key={l.value} value={l.value}>{l.label}</option>)}</select></div>
        <div><label className="block text-xs font-medium mb-1">Description</label><textarea value={f.description} onChange={e=>setF((x:any)=>({...x,description:e.target.value}))} rows={2} className={inp+" resize-none"} placeholder="Brief description..."/></div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>Cancel</Button>
          <Button size="sm" disabled={!f.name||saving} onClick={()=>onSave(f)}>{saving?"Saving...":defaultVals?"Save Changes":"Create"}</Button>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Designations" description="Job titles and levels across your organization." action={<Button icon={<Plus size={15}/>} onClick={()=>{setShowForm(true);setEditId(null);}}>New Designation</Button>}/>
      {showForm && !editId && <FormPanel onSave={b=>create.mutate(b)} onCancel={()=>setShowForm(false)} saving={create.isPending}/>}
      <div className="grid grid-cols-3 gap-4">
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]"><Briefcase size={16}/></div><div><p className="text-2xl font-semibold font-heading">{designations.length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Total Designations</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]"><Briefcase size={16} className="text-[hsl(var(--success))]"/></div><div><p className="text-2xl font-semibold font-heading">{designations.filter((d:any)=>d.is_active).length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Active</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--info-subtle))]"><Briefcase size={16} className="text-[hsl(var(--info))]"/></div><div><p className="text-2xl font-semibold font-heading">{new Set(designations.map((d:any)=>d.level)).size}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Levels</p></div></div></Card>
      </div>
      {isLoading ? <div className="space-y-2">{Array.from({length:4}).map((_,i)=><div key={i} className="h-16 rounded-xl bg-[hsl(var(--secondary))] animate-pulse"/>)}</div>
      : designations.length === 0 ? <EmptyState icon={Briefcase} title="No designations yet" description="Define job titles for your organization." action={<Button icon={<Plus size={14}/>} onClick={()=>setShowForm(true)}>Add Designation</Button>}/>
      : <div className="space-y-6">{grouped.length > 0 ? grouped.map(group=>(
        <div key={group.value}>
          <div className="flex items-center gap-2 mb-3">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[hsl(var(--primary))] text-[10px] font-bold text-[hsl(var(--primary-foreground))]">{group.value}</span>
            <h3 className="text-sm font-semibold text-[hsl(var(--foreground-subtle))]">{group.label}</h3>
          </div>
          <div className="space-y-2">
            {group.items.map((d:any) => editId===d.id ? (
              <FormPanel key={d.id} defaultVals={{name:d.name,code:d.code??"",level:d.level,description:d.description??""}} onSave={b=>update.mutate({id:d.id,b})} onCancel={()=>setEditId(null)} saving={update.isPending}/>
            ) : (
              <div key={d.id} className="group flex items-center justify-between rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-5 py-3.5 hover:border-[hsl(var(--border-strong))] transition-colors">
                <div className="flex items-center gap-3">
                  <div>
                    <div className="flex items-center gap-2"><p className="font-medium text-sm">{d.name}</p>{d.code&&<span className="font-mono text-[10px] bg-[hsl(var(--secondary))] px-1.5 py-0.5 rounded">{d.code}</span>}{!d.is_active&&<Badge variant="error">Inactive</Badge>}</div>
                    {d.description&&<p className="text-xs text-[hsl(var(--foreground-muted))] mt-0.5">{d.description}</p>}
                  </div>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={()=>setEditId(d.id)} className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))]"><Edit size={13}/></button>
                  <button onClick={()=>{if(confirm(`Delete "${d.name}"?`))remove.mutate(d.id);}} className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-[hsl(var(--status-error-bg))] text-[hsl(var(--destructive))]"><Trash2 size={13}/></button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )) : <div className="space-y-2">{designations.map((d:any)=>(
        <div key={d.id} className="group flex items-center justify-between rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-5 py-3.5 hover:border-[hsl(var(--border-strong))] transition-colors">
          <p className="font-medium text-sm">{d.name}</p>
          <button onClick={()=>{if(confirm(`Delete "${d.name}"?`))remove.mutate(d.id);}} className="opacity-0 group-hover:opacity-100 flex h-7 w-7 items-center justify-center rounded-md hover:bg-[hsl(var(--status-error-bg))] text-[hsl(var(--destructive))]"><Trash2 size={13}/></button>
        </div>
      ))}</div>}</div>}
    </div>
  );
}
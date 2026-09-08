"use client";
import { useState } from "react";
import { Building2, Plus, Users, Edit, Trash2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button, Card, EmptyState, PageHeader } from "@/components/atoms";
import { cn } from "@/utils/cn";

interface Department { id: string; name: string; code: string | null; description: string | null; is_active: boolean; }

function DeptForm({ onSubmit, onCancel, defaultValues, isLoading }: { onSubmit: (d: {name:string;code:string;description:string}) => void; onCancel: () => void; defaultValues?: {name?:string;code?:string;description?:string}; isLoading?: boolean }) {
  const [name, setName] = useState(defaultValues?.name ?? "");
  const [code, setCode] = useState(defaultValues?.code ?? "");
  const [desc, setDesc] = useState(defaultValues?.description ?? "");
  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";
  return (
    <div className="space-y-4 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 shadow-sm">
      <h3 className="font-heading text-sm font-semibold">{defaultValues ? "Edit Department" : "New Department"}</h3>
      <div className="grid grid-cols-2 gap-4">
        <div><label className="block text-xs font-medium mb-1">Name *</label><input value={name} onChange={e=>setName(e.target.value)} placeholder="Engineering" className={inp}/></div>
        <div><label className="block text-xs font-medium mb-1">Code</label><input value={code} onChange={e=>setCode(e.target.value.toUpperCase())} placeholder="ENG" className={inp}/></div>
      </div>
      <div><label className="block text-xs font-medium mb-1">Description</label><textarea value={desc} onChange={e=>setDesc(e.target.value)} rows={2} placeholder="Brief description..." className={cn(inp,"resize-none")}/></div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onCancel}>Cancel</Button>
        <Button size="sm" disabled={!name.trim()||isLoading} onClick={()=>onSubmit({name,code,description:desc})}>{isLoading?"Saving...":defaultValues?"Save Changes":"Create"}</Button>
      </div>
    </div>
  );
}

export default function DepartmentsPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string|null>(null);
  const { data, isLoading } = useQuery({ queryKey: ["departments"], queryFn: async () => { const {data} = await apiClient.get("/departments"); return data; } });
  const create = useMutation({ mutationFn: (b:object) => apiClient.post("/departments",b), onSuccess: () => { toast.success("Department created"); void qc.invalidateQueries({queryKey:["departments"]}); setShowForm(false); } });
  const update = useMutation({ mutationFn: ({id,body}:{id:string;body:object}) => apiClient.patch(`/departments/${id}`,body), onSuccess: () => { toast.success("Updated"); void qc.invalidateQueries({queryKey:["departments"]}); setEditId(null); } });
  const remove = useMutation({ mutationFn: (id:string) => apiClient.delete(`/departments/${id}`), onSuccess: () => { toast.success("Deleted"); void qc.invalidateQueries({queryKey:["departments"]}); }, onError: () => toast.error("Cannot delete — employees assigned") });
  const depts: Department[] = data?.items ?? [];
  return (
    <div className="space-y-6">
      <PageHeader title="Departments" description="Organize your workforce into departments." action={<Button icon={<Plus size={15}/>} onClick={()=>{setShowForm(true);setEditId(null);}}>New Department</Button>}/>
      {showForm && !editId && <DeptForm onSubmit={d=>create.mutate(d)} onCancel={()=>setShowForm(false)} isLoading={create.isPending}/>}
      <div className="grid grid-cols-3 gap-4">
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]"><Building2 size={16} className="text-[hsl(var(--foreground-subtle))]"/></div><div><p className="text-2xl font-semibold font-heading">{depts.length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Departments</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]"><Users size={16} className="text-[hsl(var(--success))]"/></div><div><p className="text-2xl font-semibold font-heading">{depts.filter(d=>d.is_active).length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Active</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--warning-subtle))]"><Building2 size={16} className="text-[hsl(var(--warning))]"/></div><div><p className="text-2xl font-semibold font-heading">{depts.filter(d=>!d.is_active).length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Inactive</p></div></div></Card>
      </div>
      {isLoading ? <div className="space-y-2">{Array.from({length:5}).map((_,i)=><div key={i} className="h-16 rounded-xl bg-[hsl(var(--secondary))] animate-pulse"/>)}</div>
      : depts.length===0 ? <EmptyState icon={Building2} title="No departments yet" description="Create your first department." action={<Button icon={<Plus size={14}/>} onClick={()=>setShowForm(true)}>Create Department</Button>}/>
      : <div className="space-y-2">{depts.map(dept=>(
        <div key={dept.id}>
          {editId===dept.id ? <DeptForm defaultValues={{name:dept.name,code:dept.code??"",description:dept.description??""}} onSubmit={b=>update.mutate({id:dept.id,body:b})} onCancel={()=>setEditId(null)} isLoading={update.isPending}/>
          : <div className="group flex items-center justify-between rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-5 py-4 shadow-sm hover:border-[hsl(var(--border-strong))] transition-colors">
              <div className="flex items-center gap-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]"><Building2 size={18} className="text-[hsl(var(--foreground-subtle))]"/></div>
                <div><div className="flex items-center gap-2"><p className="font-medium text-sm">{dept.name}</p>{dept.code&&<span className="font-mono text-[10px] rounded bg-[hsl(var(--secondary))] px-1.5 py-0.5 text-[hsl(var(--foreground-muted))]">{dept.code}</span>}</div>{dept.description&&<p className="text-xs text-[hsl(var(--foreground-muted))] mt-0.5">{dept.description}</p>}</div>
              </div>
              <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={()=>setEditId(dept.id)} className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))]"><Edit size={13}/></button>
                <button onClick={()=>{if(confirm(`Delete "${dept.name}"?`))remove.mutate(dept.id);}} className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-[hsl(var(--status-error-bg))] text-[hsl(var(--destructive))]"><Trash2 size={13}/></button>
              </div>
            </div>}
        </div>
      ))}</div>}
    </div>
  );
}